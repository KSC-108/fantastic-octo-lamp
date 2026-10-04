"""Walk-forward signal generation: every out-of-sample probability comes from a model that
had no access to its own outcome. Training rows are embargoed by the longest label horizon."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

from octoquant.config import Config
from octoquant.data.base import DataPanel
from octoquant.features import build_features, build_labels, build_regime_labels
from octoquant.models import ProbabilityBank


@dataclass
class Dataset:
    panel: DataPanel
    feats: pd.DataFrame
    mkt: pd.DataFrame
    labels: pd.DataFrame
    regime: pd.Series

    @property
    def dates(self) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(sorted(self.feats["date"].unique()))


def build_dataset(panel: DataPanel, cfg: Config) -> Dataset:
    feats, mkt = build_features(panel)
    labels = build_labels(panel, feats, cfg.model, cfg.costs)
    regime = build_regime_labels(panel.index, cfg.model)
    return Dataset(panel, feats, mkt, labels, regime)


def walk_forward_signals(
    ds: Dataset, cfg: Config, progress: Callable[[str], None] | None = None
) -> pd.DataFrame:
    """Signals for every date after the initial training window, refit every `retrain_every`."""
    m = cfg.model
    dates = ds.dates
    first = m.min_train_days + m.embargo
    if len(dates) <= first + m.retrain_every:
        raise ValueError(f"need more than {first + m.retrain_every} trading days, have {len(dates)}")
    out = []
    for start in range(first, len(dates), m.retrain_every):
        block = dates[start : start + m.retrain_every]
        train_end = dates[start - m.embargo]
        bank = ProbabilityBank(m).fit(ds.feats, ds.labels, ds.mkt, ds.regime, train_end)
        rows = ds.feats[ds.feats["date"].isin(block)]
        out.append(bank.predict(rows, ds.mkt))
        if progress:
            progress(f"walk-forward block {block[0].date()} to {block[-1].date()}")
    signals = pd.concat(out, ignore_index=True)
    return signals.sort_values(["date", "symbol"]).reset_index(drop=True)


def fit_final_bank(ds: Dataset, cfg: Config) -> tuple[ProbabilityBank, pd.Timestamp]:
    """Production model: trained on everything whose labels have resolved."""
    dates = ds.dates
    train_end = dates[-1 - cfg.model.embargo]
    bank = ProbabilityBank(cfg.model).fit(ds.feats, ds.labels, ds.mkt, ds.regime, train_end)
    return bank, train_end
