"""The decision rule: fire only when every probability clears its validated threshold."""

from __future__ import annotations

import numpy as np

from octoquant.config import StrategyParams


def fire_mask(sig: dict[str, np.ndarray], p: StrategyParams) -> np.ndarray:
    """Boolean mask over a day's signal arrays. All conditions must hold."""
    m = (
        (sig["p_up"] >= p.tau_dir)
        & (sig["p_bp"] >= p.tau_bp)
        & (sig["sq"] >= p.tau_sq)
        & (sig["p_stressed"] <= p.max_stressed)
        & (sig["p_bear"] <= p.max_bear)
    )
    if p.max_gap is not None:
        m &= np.abs(sig["gap"]) <= p.max_gap
    if p.max_vol20 is not None:
        m &= sig["vol_20"] <= p.max_vol20
    return m & np.isfinite(sig["atr_pct"]) & (sig["atr_pct"] > 0)


def rank_score(sig: dict[str, np.ndarray]) -> np.ndarray:
    """Order candidates by conviction when risk limits force a choice."""
    return sig["p_up"] * sig["sq"]
