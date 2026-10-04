"""Calibration: does a stated 60% mean 60%? Brier score, ECE, reliability, gating."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.linear_model import LogisticRegression

from octoquant.config import CalibrationGateConfig


def brier_score(p: np.ndarray, y: np.ndarray) -> float:
    """Binary Brier score. p is P(event), y is 0/1."""
    p, y = np.asarray(p, float), np.asarray(y, float)
    return float(np.mean((p - y) ** 2))


def reliability_table(p: np.ndarray, y: np.ndarray, bins: int = 10) -> list[dict]:
    p, y = np.asarray(p, float), np.asarray(y, float)
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    rows = []
    for b in range(bins):
        m = idx == b
        if m.any():
            rows.append(
                {"bin": b, "lo": edges[b], "hi": edges[b + 1], "n": int(m.sum()),
                 "mean_p": float(p[m].mean()), "freq": float(y[m].mean())}
            )
    return rows


def ece(p: np.ndarray, y: np.ndarray, bins: int = 10) -> float:
    """Expected calibration error: sample-weighted gap between stated and realised frequency."""
    rows = reliability_table(p, y, bins)
    n = sum(r["n"] for r in rows)
    if n == 0:
        return float("nan")
    return float(sum(r["n"] * abs(r["mean_p"] - r["freq"]) for r in rows) / n)


class VectorScaler:
    """Multinomial Platt-style recalibration: logistic regression on log-probabilities.

    Few parameters, so it stays stable on the short calibration slices a walk-forward
    leaves, where isotonic regression overfits.
    """

    def __init__(self, n_classes: int):
        self.n_classes = n_classes
        self.lr: LogisticRegression | None = None

    @staticmethod
    def _z(probs: np.ndarray) -> np.ndarray:
        return np.log(np.clip(probs, 1e-4, 1.0))

    def fit(self, probs: np.ndarray, y: np.ndarray) -> VectorScaler:
        if len(np.unique(y)) == self.n_classes:
            self.lr = LogisticRegression(C=1.0, max_iter=500).fit(self._z(probs), y)
        return self

    def transform(self, probs: np.ndarray) -> np.ndarray:
        if self.lr is None:
            return probs
        return self.lr.predict_proba(self._z(probs))


@dataclass
class CalibrationReport:
    ok: bool
    ece: float
    brier: float
    n: int
    reason: str

    def as_dict(self) -> dict:
        return {"ok": self.ok, "ece": self.ece, "brier": self.brier, "n": self.n,
                "reason": self.reason}


def assess_calibration(p: np.ndarray, y: np.ndarray, cfg: CalibrationGateConfig) -> CalibrationReport:
    """Gate: enough resolved samples and ECE under the limit. Failing sets sizing to zero."""
    p, y = np.asarray(p, float), np.asarray(y, float)
    m = ~(np.isnan(p) | np.isnan(y))
    p, y = p[m], y[m]
    n = int(len(p))
    if n < cfg.min_samples:
        return CalibrationReport(False, float("nan"), float("nan"), n,
                                 f"only {n} resolved samples, need {cfg.min_samples}")
    e, b = ece(p, y), brier_score(p, y)
    if e > cfg.max_ece:
        return CalibrationReport(False, e, b, n, f"ECE {e:.3f} above limit {cfg.max_ece:.3f}")
    return CalibrationReport(True, e, b, n, "calibrated")
