"""Probability layer: five fixed questions, each answered by an isolated calibrated model.

`ProbabilityBank` is the default implementation of the slot the source design calls "Jev".
Any object with the same `fit` / `predict` shape (for example a wrapper over an external SDK)
can replace it: the rest of the system only consumes the signals frame.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from octoquant.calibration import VectorScaler
from octoquant.config import ModelConfig
from octoquant.features import FEATURE_COLUMNS, MARKET_FEATURE_COLUMNS

# question -> (classes, label column)
QUESTIONS = {
    "dir": ([0.0, 1.0, 2.0], "y_dir"),
    "bp": ([0.0, 1.0], "y_bp"),
    "sq": ([0.0, 1.0], "y_sq"),
    "risk": ([0.0, 1.0, 2.0], "y_risk"),
}


def _gbm(cfg: ModelConfig) -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        max_iter=cfg.max_iter, learning_rate=0.06, max_depth=3, min_samples_leaf=100,
        l2_regularization=1.0, random_state=cfg.seed,
    )


class CalibratedClassifier:
    """Gradient boosting with recalibration fitted on a later, embargoed slice of time."""

    def __init__(self, classes: list[float], cfg: ModelConfig):
        self.classes = classes
        self.cfg = cfg
        self.base = None
        self.prior = np.full(len(classes), 1.0 / len(classes))
        self.calibrator: VectorScaler | None = None

    def _raw(self, X: np.ndarray) -> np.ndarray:
        if self.base is None:
            return np.tile(self.prior, (len(X), 1))
        raw = self.base.predict_proba(X)
        out = np.zeros((len(X), len(self.classes)))
        for j, c in enumerate(self.base.classes_):
            out[:, self.classes.index(c)] = raw[:, j]
        return out

    def fit(self, X: np.ndarray, y: np.ndarray, dates: np.ndarray) -> CalibratedClassifier:
        ok = ~np.isnan(y)
        X, y, dates = X[ok], y[ok], dates[ok]
        ud = np.unique(dates)
        n_cal = max(1, int(len(ud) * self.cfg.cal_frac))
        cut_train = len(ud) - n_cal - self.cfg.embargo
        if cut_train < 50:
            raise ValueError("not enough history to train and calibrate")
        train = dates <= ud[cut_train - 1]
        cal = dates >= ud[-n_cal]
        counts = np.array([(y[train] == c).sum() for c in self.classes], float)
        self.prior = (counts + 1) / (counts + 1).sum()
        if (counts > 0).sum() < 2:
            return self
        self.base = _gbm(self.cfg).fit(X[train], y[train])
        raw = self._raw(X[cal])
        self.calibrator = VectorScaler(len(self.classes)).fit(
            raw, np.searchsorted(self.classes, y[cal])
        )
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        raw = self._raw(X)
        return self.calibrator.transform(raw) if self.calibrator else raw


class RegimeModel:
    """Market-level regime (bear, chop, bull) from index and breadth features."""

    classes = [0.0, 1.0, 2.0]

    def __init__(self, cfg: ModelConfig):
        self.cfg = cfg
        self.pipe = make_pipeline(
            SimpleImputer(strategy="median"), StandardScaler(),
            LogisticRegression(C=0.5, max_iter=500),
        )
        self.fitted = False
        self.prior = np.array([1 / 3, 1 / 3, 1 / 3])

    def fit(self, mkt: pd.DataFrame, labels: pd.Series, last_train_date: pd.Timestamp):
        df = mkt.join(labels.rename("y")).dropna(subset=["y"])
        df = df[df.index <= last_train_date]
        if len(df) < 100 or df["y"].nunique() < 2:
            return self
        self.pipe.fit(df[MARKET_FEATURE_COLUMNS], df["y"])
        self.fitted = True
        return self

    def predict_proba(self, mkt: pd.DataFrame) -> pd.DataFrame:
        if not self.fitted:
            out = np.tile(self.prior, (len(mkt), 1))
        else:
            raw = self.pipe.predict_proba(mkt[MARKET_FEATURE_COLUMNS])
            out = np.zeros((len(mkt), 3))
            for j, c in enumerate(self.pipe.classes_):
                out[:, int(c)] = raw[:, j]
        return pd.DataFrame(out, index=mkt.index, columns=["p_bear", "p_chop", "p_bull"])


class ProbabilityBank:
    """Fits the five question models and turns snapshots into a signals frame."""

    def __init__(self, cfg: ModelConfig):
        self.cfg = cfg
        self.models: dict[str, CalibratedClassifier] = {}
        self.regime = RegimeModel(cfg)

    def fit(
        self,
        feats: pd.DataFrame,
        labels: pd.DataFrame,
        mkt: pd.DataFrame,
        regime_labels: pd.Series,
        last_train_date: pd.Timestamp,
    ) -> ProbabilityBank:
        """Trains on rows with date <= last_train_date. The caller supplies an embargoed date."""
        data = feats.merge(labels, on=["date", "symbol"], how="left")
        data = data[data["date"] <= last_train_date].sort_values("date")
        X = data[FEATURE_COLUMNS].to_numpy(float)
        dates = data["date"].to_numpy()
        for name, (classes, col) in QUESTIONS.items():
            self.models[name] = CalibratedClassifier(classes, self.cfg).fit(
                X, data[col].to_numpy(float), dates
            )
        self.regime.fit(mkt, regime_labels, last_train_date)
        return self

    def predict(self, feats: pd.DataFrame, mkt: pd.DataFrame) -> pd.DataFrame:
        X = feats[FEATURE_COLUMNS].to_numpy(float)
        p = {k: m.predict_proba(X) for k, m in self.models.items()}
        out = feats[["date", "symbol", "atr_pct", "gap", "vol_20"]].copy().reset_index(drop=True)
        out["p_down"], out["p_flat"], out["p_up"] = p["dir"][:, 0], p["dir"][:, 1], p["dir"][:, 2]
        out["p_bp"] = p["bp"][:, 1]
        out["sq"] = p["sq"][:, 1]
        out["p_calm"], out["p_normal"], out["p_stressed"] = (
            p["risk"][:, 0], p["risk"][:, 1], p["risk"][:, 2]
        )
        reg = self.regime.predict_proba(mkt.reindex(pd.DatetimeIndex(out["date"].unique())))
        return out.merge(reg.reset_index(names="date"), on="date", how="left")
