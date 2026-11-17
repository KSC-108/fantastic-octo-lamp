"""Strategy templates: legs placed relative to the at-the-money strike, and expiry payoff.

A leg's offset is in strike steps: `w` is the short-strike distance (width_steps), `g` the hedge
distance beyond it (wing_steps). side +1 buys, -1 sells. Every template uses one lot per leg;
the sizer scales the whole structure.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class LegTemplate:
    kind: str       # CE or PE
    side: int       # +1 long, -1 short
    offset: str     # expression in w, g: "0", "w", "-w", "w+g", "-w-g", "g", "-g"


@dataclass(frozen=True)
class StrategySpec:
    name: str
    label: str
    legs: tuple[LegTemplate, ...]
    view: str        # neutral, bullish, bearish, volatile
    defined_risk: bool

    @property
    def credit(self) -> bool:
        """Premium-selling structure: more short legs than long legs nearer the money."""
        return sum(leg.side for leg in self.legs) < 0 or self.name in CREDIT_SPREADS

    def offsets(self, w: int, g: int) -> list[tuple[str, int, int]]:
        out = []
        for leg in self.legs:
            out.append((leg.kind, leg.side, _offset_steps(leg.offset, w, g)))
        return out


def _offset_steps(expr: str, w: int, g: int) -> int:
    """Evaluate a signed sum of the terms 0, w and g, e.g. "-w-g"."""
    total, sign, vals = 0, 1, {"0": 0, "w": w, "g": g}
    for ch in expr.replace(" ", ""):
        if ch in "+-":
            sign = 1 if ch == "+" else -1
        elif ch in vals:
            total, sign = total + sign * vals[ch], 1
        else:
            raise ValueError(f"bad leg offset {expr!r}")
    return total


CREDIT_SPREADS = {"iron_condor", "iron_butterfly", "bull_put_spread", "bear_call_spread"}
L = LegTemplate
STRATEGIES: dict[str, StrategySpec] = {s.name: s for s in [
    StrategySpec("iron_condor", "Iron condor",
                 (L("PE", 1, "-w-g"), L("PE", -1, "-w"), L("CE", -1, "w"), L("CE", 1, "w+g")),
                 "neutral", True),
    StrategySpec("iron_butterfly", "Iron butterfly",
                 (L("PE", 1, "-g"), L("PE", -1, "0"), L("CE", -1, "0"), L("CE", 1, "g")),
                 "neutral", True),
    StrategySpec("short_strangle", "Short strangle", (L("PE", -1, "-w"), L("CE", -1, "w")),
                 "neutral", False),
    StrategySpec("short_straddle", "Short straddle", (L("PE", -1, "0"), L("CE", -1, "0")),
                 "neutral", False),
    StrategySpec("long_straddle", "Long straddle", (L("PE", 1, "0"), L("CE", 1, "0")),
                 "volatile", True),
    StrategySpec("long_strangle", "Long strangle", (L("PE", 1, "-w"), L("CE", 1, "w")),
                 "volatile", True),
    StrategySpec("bull_put_spread", "Bull put spread", (L("PE", 1, "-w-g"), L("PE", -1, "-w")),
                 "bullish", True),
    StrategySpec("bear_call_spread", "Bear call spread", (L("CE", -1, "w"), L("CE", 1, "w+g")),
                 "bearish", True),
    StrategySpec("bull_call_spread", "Bull call spread", (L("CE", 1, "0"), L("CE", -1, "g")),
                 "bullish", True),
    StrategySpec("bear_put_spread", "Bear put spread", (L("PE", 1, "0"), L("PE", -1, "-g")),
                 "bearish", True),
]}


def leg_payoff(kind: str, side: int, strike: float, premium: float, s: np.ndarray) -> np.ndarray:
    intrinsic = np.maximum(s - strike, 0.0) if kind == "CE" else np.maximum(strike - s, 0.0)
    return side * (intrinsic - premium)


def payoff_curve(legs: list[dict], s: np.ndarray) -> np.ndarray:
    """Expiry P&L per unit for legs [{kind, side, strike, premium}], before costs."""
    out = np.zeros_like(s, dtype=float)
    for leg in legs:
        out += leg_payoff(leg["kind"], leg["side"], leg["strike"], leg["premium"], s)
    return out


def payoff_extremes(legs: list[dict], spot: float) -> tuple[float, float, list[float]]:
    """(max profit, max loss as a positive number, breakevens) per unit at expiry.

    Infinite tails show up as a slope at the edge of the grid and are reported as inf."""
    ks = [leg["strike"] for leg in legs]
    lo, hi = min(ks + [spot]) * 0.5, max(ks + [spot]) * 1.5
    s = np.linspace(lo, hi, 4001)
    pnl = payoff_curve(legs, s)
    net_call = sum(leg["side"] for leg in legs if leg["kind"] == "CE")
    net_put = sum(leg["side"] for leg in legs if leg["kind"] == "PE")
    max_profit = float("inf") if net_call > 0 or net_put > 0 else float(pnl.max())
    max_loss = float("inf") if net_call < 0 or net_put < 0 else float(max(-pnl.min(), 0.0))
    sign = np.sign(pnl)
    idx = np.where(np.diff(sign) != 0)[0]
    bes: list[float] = []
    tol = (hi - lo) / 1000
    for i in idx:
        b = float(s[i] - pnl[i] * (s[i + 1] - s[i]) / (pnl[i + 1] - pnl[i]))
        if not bes or abs(b - bes[-1]) > tol:  # a grid point exactly at zero is seen twice
            bes.append(b)
    return max_profit, max_loss, bes
