"""Position sizing: capped fractional Kelly. Plain arithmetic, no model involved."""

from __future__ import annotations

from octoquant.config import RiskConfig, SizingConfig


def kelly_fraction(p_win: float, payoff: float) -> float:
    """Full-Kelly stake for win probability p and win/loss payoff ratio b."""
    return (p_win * payoff - (1.0 - p_win)) / payoff


def p_win_from_signal(p_up: float, p_flat: float) -> float:
    """P(trade ends profitable). The flat band straddles zero, so half of it counts (assumption)."""
    return p_up + 0.5 * p_flat


def position_fraction(
    p_win: float,
    target_atr: float,
    stop_atr: float,
    sizing: SizingConfig,
    risk: RiskConfig,
    calibration_ok: bool,
) -> float:
    """Fraction of equity to commit. Zero when uncalibrated, below the cutoff, or no edge."""
    if not calibration_ok or p_win < sizing.min_p:
        return 0.0
    payoff = min(max(target_atr / stop_atr, sizing.payoff_floor), sizing.payoff_cap)
    full = kelly_fraction(p_win, payoff)
    if full <= 0:
        return 0.0
    return min(full * sizing.kelly_fraction, risk.max_position_pct)
