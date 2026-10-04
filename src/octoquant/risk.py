"""Hard risk limits. Deterministic, model-free, and checked before every order.

Nothing in the probability layer or the slow brain can modify these values at runtime.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from octoquant.config import RiskConfig


@dataclass
class RiskState:
    peak_equity: float
    prev_equity: float
    kill_switch: bool = False
    kill_reason: str = ""
    halt_date: str | None = None


class RiskManager:
    def __init__(self, cfg: RiskConfig, initial_equity: float, state: RiskState | None = None):
        self.cfg = cfg
        self.state = state or RiskState(peak_equity=initial_equity, prev_equity=initial_equity)

    def end_of_day(self, date: str, equity: float) -> list[str]:
        """Update drawdown and daily loss after the close. Returns human-readable events."""
        s, events = self.state, []
        s.peak_equity = max(s.peak_equity, equity)
        drawdown = 1.0 - equity / s.peak_equity
        day_ret = equity / s.prev_equity - 1.0
        s.prev_equity = equity
        if day_ret <= -self.cfg.daily_loss_limit_pct and s.halt_date != date:
            s.halt_date = date
            events.append(f"daily loss limit hit ({day_ret:.2%}): no new entries")
        if drawdown >= self.cfg.max_drawdown_pct and not s.kill_switch:
            s.kill_switch = True
            s.kill_reason = f"drawdown {drawdown:.2%} reached limit {self.cfg.max_drawdown_pct:.0%}"
            events.append(f"KILL SWITCH: {s.kill_reason}")
        return events

    def trip(self, reason: str) -> None:
        """Manual or external kill switch."""
        self.state.kill_switch = True
        self.state.kill_reason = reason

    def clear(self) -> None:
        """Human action only. Resets the peak so one drawdown does not re-trip immediately."""
        self.state.kill_switch = False
        self.state.kill_reason = ""
        self.state.peak_equity = self.state.prev_equity

    def entries_allowed(self, date: str) -> bool:
        return not self.state.kill_switch and self.state.halt_date != date

    def clip_notional(
        self, desired: float, equity: float, gross_value: float, n_positions: int
    ) -> tuple[float, str | None]:
        """Cut an order to the position cap and gross-exposure room. Returns (notional, reason)."""
        if n_positions >= self.cfg.max_positions:
            return 0.0, "max open positions reached"
        room = self.cfg.max_gross_pct * equity - gross_value
        if room <= 0:
            return 0.0, "gross exposure cap reached"
        capped = min(desired, self.cfg.max_position_pct * equity, room)
        return capped, None

    def needs_approval(self, notional: float) -> bool:
        return notional > self.cfg.manual_approval_above

    def to_dict(self) -> dict:
        return asdict(self.state)
