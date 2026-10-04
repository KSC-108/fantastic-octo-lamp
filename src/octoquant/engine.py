"""Portfolio simulator. One `step()` per trading day, used by BOTH the backtest and the paper
runner so the two cannot diverge.

Timing: signals are computed at the close of day t. Orders fill at the open of day t+1 with
slippage. Stops and targets are checked against day highs and lows, gap-aware, and a bar that
touches both stop and target is resolved as a stop (conservative).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from octoquant.config import Config, CostConfig, RiskConfig, SizingConfig, StrategyParams
from octoquant.costs import slipped_price, trade_costs
from octoquant.decision import fire_mask, rank_score
from octoquant.risk import RiskManager, RiskState
from octoquant.sizing import p_win_from_signal, position_fraction

Bar = tuple[float, float, float, float]  # open, high, low, close
MIN_ORDER_NOTIONAL = 5_000.0


@dataclass
class Position:
    symbol: str
    shares: int
    entry_px: float
    entry_date: str
    entry_costs: float
    stop: float
    target: float
    p_up: float
    days_held: int = 0
    last_close: float = 0.0
    decided: str = ""


@dataclass
class Order:
    symbol: str
    notional: float
    atr_pct: float
    p_up: float
    p_win: float
    decided: str


@dataclass
class Trade:
    symbol: str
    entry_date: str
    exit_date: str
    shares: int
    entry_px: float
    exit_px: float
    pnl: float
    ret: float
    days: int
    reason: str
    p_up: float
    decided: str = ""


@dataclass
class StepResult:
    date: str
    equity: float
    cash: float
    exposure: float
    fills: list[dict] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)
    held_orders: list[Order] = field(default_factory=list)


class BarIndex:
    """date -> symbol -> (o, h, l, c), built once and reused across trials."""

    def __init__(self, stocks: pd.DataFrame):
        self.by_date: dict[pd.Timestamp, dict[str, Bar]] = {}
        for r in stocks.itertuples(index=False):
            self.by_date.setdefault(r.date, {})[r.symbol] = (r.open, r.high, r.low, r.close)

    def dates(self) -> list[pd.Timestamp]:
        return sorted(self.by_date)


class SignalIndex:
    """date -> dict of numpy arrays, so a day's rule evaluates without pandas overhead."""

    COLS = ("p_up", "p_flat", "p_bp", "sq", "p_stressed", "p_bear", "gap", "vol_20", "atr_pct")

    def __init__(self, signals: pd.DataFrame):
        self.by_date: dict[pd.Timestamp, dict[str, np.ndarray]] = {}
        for d, g in signals.groupby("date"):
            arrs = {c: g[c].to_numpy(float) for c in self.COLS}
            arrs["symbol"] = g["symbol"].to_numpy()
            self.by_date[d] = arrs


class PortfolioSim:
    def __init__(
        self,
        params: StrategyParams,
        costs: CostConfig,
        risk: RiskConfig,
        sizing: SizingConfig,
        initial_equity: float,
        risk_state: RiskState | None = None,
    ):
        self.params, self.costs, self.sizing = params, costs, sizing
        self.risk = RiskManager(risk, initial_equity, risk_state)
        self.cash = initial_equity
        self.positions: dict[str, Position] = {}
        self.pending_entries: list[Order] = []
        self.pending_exits: dict[str, str] = {}
        self.trades: list[Trade] = []

    # ---- persistence (paper runner) -------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "cash": self.cash,
            "positions": {k: asdict(v) for k, v in self.positions.items()},
            "pending_entries": [asdict(o) for o in self.pending_entries],
            "pending_exits": self.pending_exits,
            "risk": self.risk.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict, cfg: Config, params: StrategyParams) -> PortfolioSim:
        sim = cls(params, cfg.costs, cfg.risk, cfg.sizing, d["cash"], RiskState(**d["risk"]))
        sim.cash = d["cash"]
        sim.positions = {k: Position(**v) for k, v in d["positions"].items()}
        sim.pending_entries = [Order(**o) for o in d["pending_entries"]]
        sim.pending_exits = dict(d["pending_exits"])
        return sim

    # ---- internals -------------------------------------------------------------------------
    def _sell(self, sym: str, raw_px: float, date: str, reason: str, fills: list[dict]) -> None:
        pos = self.positions.pop(sym)
        px = slipped_price(raw_px, "sell", self.costs)
        gross = pos.shares * px
        fee = trade_costs("sell", gross, self.costs)
        self.cash += gross - fee
        cost_basis = pos.shares * pos.entry_px + pos.entry_costs
        pnl = gross - fee - cost_basis
        self.trades.append(
            Trade(sym, pos.entry_date, date, pos.shares, pos.entry_px, px, pnl, pnl / cost_basis,
                  pos.days_held, reason, pos.p_up, pos.decided)
        )
        self.pending_exits.pop(sym, None)
        fills.append({"date": date, "symbol": sym, "side": "sell", "shares": pos.shares,
                      "price": px, "costs": fee, "reason": reason})

    def _buy(self, order: Order, open_px: float, date: str, fills: list[dict]) -> bool:
        px = slipped_price(open_px, "buy", self.costs)
        budget = min(order.notional, self.cash)
        shares = int(budget // px)
        while shares > 0 and shares * px + trade_costs("buy", shares * px, self.costs) > self.cash:
            shares -= 1
        if shares < 1:
            return False
        gross = shares * px
        fee = trade_costs("buy", gross, self.costs)
        self.cash -= gross + fee
        p = self.params
        self.positions[order.symbol] = Position(
            order.symbol, shares, px, date, fee,
            stop=px * (1 - p.stop_atr * order.atr_pct),
            target=px * (1 + p.target_atr * order.atr_pct),
            p_up=order.p_up, last_close=px, decided=order.decided,
        )
        fills.append({"date": date, "symbol": order.symbol, "side": "buy", "shares": shares,
                      "price": px, "costs": fee, "reason": "entry"})
        return True

    def equity(self) -> float:
        return self.cash + sum(p.shares * p.last_close for p in self.positions.values())

    def gross_value(self) -> float:
        return sum(p.shares * p.last_close for p in self.positions.values())

    # ---- the daily step --------------------------------------------------------------------
    def step(
        self,
        date: pd.Timestamp,
        bars: dict[str, Bar],
        signals: dict[str, np.ndarray] | None,
        calibration_ok: bool = True,
        approve: Callable[[Order], bool] | None = None,
        record_decisions: bool = False,
    ) -> StepResult:
        d = date.strftime("%Y-%m-%d")
        fills: list[dict] = []
        events: list[str] = []

        # 1. open: queued exits, then queued entries
        for sym, reason in list(self.pending_exits.items()):
            if sym in self.positions and sym in bars:
                self._sell(sym, bars[sym][0], d, reason, fills)
        if not self.risk.state.kill_switch:
            for order in self.pending_entries:
                if order.symbol in bars and order.symbol not in self.positions:
                    if not self._buy(order, bars[order.symbol][0], d, fills):
                        events.append(f"{order.symbol}: entry skipped, insufficient cash")
        self.pending_entries = []

        # 2. intraday: stops and targets against the day's range
        for sym in list(self.positions):
            bar = bars.get(sym)
            if bar is None:
                continue  # no bar (halt/circuit): cannot exit, carry the position
            o, h, low, _ = bar
            pos = self.positions[sym]
            fresh = pos.entry_date == d
            if not fresh and o <= pos.stop:
                self._sell(sym, o, d, "stop (gap)", fills)
            elif low <= pos.stop:
                self._sell(sym, pos.stop, d, "stop", fills)
            elif h >= pos.target:
                self._sell(sym, pos.target, d, "target", fills)

        # 3. close: mark, age, time stops
        for sym, pos in self.positions.items():
            bar = bars.get(sym)
            if bar is not None:
                pos.last_close = bar[3]
            pos.days_held += 1
            if pos.days_held >= self.params.max_hold:
                self.pending_exits.setdefault(sym, "time")
        equity = self.equity()

        # 4. risk after the close
        events += self.risk.end_of_day(d, equity)
        if self.risk.state.kill_switch:
            for sym in self.positions:
                self.pending_exits[sym] = "kill switch"
            self.pending_entries = []

        # 5. new entries for tomorrow's open
        decisions: list[dict] = []
        held: list[Order] = []
        if signals is not None:
            mask = fire_mask(signals, self.params)
            allowed = self.risk.entries_allowed(d)
            order_idx = np.argsort(-rank_score(signals))
            gross = self.gross_value() + sum(o.notional for o in self.pending_entries)
            for i in order_idx:
                sym = str(signals["symbol"][i])
                action, size = "no signal", 0.0
                if mask[i]:
                    if not allowed:
                        action = "blocked: " + (
                            "kill switch" if self.risk.state.kill_switch else "daily loss limit"
                        )
                    elif sym in self.positions or sym in self.pending_exits:
                        action = "skip: already held"
                    else:
                        p_win = p_win_from_signal(signals["p_up"][i], signals["p_flat"][i])
                        size = position_fraction(
                            p_win, self.params.target_atr, self.params.stop_atr,
                            self.sizing, self.risk.cfg, calibration_ok,
                        )
                        if size <= 0:
                            action = "skip: zero size" + ("" if calibration_ok else " (calibration)")
                        else:
                            n_open = len(self.positions) - len(self.pending_exits) + len(
                                self.pending_entries
                            )
                            notional, why = self.risk.clip_notional(size * equity, equity, gross,
                                                                    n_open)
                            if why or notional < MIN_ORDER_NOTIONAL:
                                action = "veto: " + (why or "order too small")
                            else:
                                order = Order(sym, notional, float(signals["atr_pct"][i]),
                                              float(signals["p_up"][i]), float(p_win), d)
                                if self.risk.needs_approval(notional) and approve is not None \
                                        and not approve(order):
                                    held.append(order)
                                    action = "held: manual approval"
                                else:
                                    self.pending_entries.append(order)
                                    gross += notional
                                    action = "order"
                if record_decisions:
                    decisions.append(
                        {"symbol": sym, "p_up": float(signals["p_up"][i]),
                         "p_bp": float(signals["p_bp"][i]), "sq": float(signals["sq"][i]),
                         "p_bear": float(signals["p_bear"][i]),
                         "p_stressed": float(signals["p_stressed"][i]),
                         "fired": bool(mask[i]), "size_frac": round(float(size), 5),
                         "action": action}
                    )

        return StepResult(d, equity, self.cash, self.gross_value() / equity, fills, events,
                          decisions, held)


@dataclass
class BacktestResult:
    equity: pd.Series
    exposure: pd.Series
    trades: pd.DataFrame
    events: list[str]


def run_backtest(
    bars: BarIndex,
    sigs: SignalIndex,
    params: StrategyParams,
    cfg: Config,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    calibration_ok: pd.Series | None = None,
    initial_equity: float | None = None,
) -> BacktestResult:
    eq0 = initial_equity or cfg.runtime.initial_equity
    sim = PortfolioSim(params, cfg.costs, cfg.risk, cfg.sizing, eq0)
    dates = [
        d for d in bars.dates()
        if (start is None or d >= start) and (end is None or d <= end)
    ]
    equity, exposure, events = {}, {}, []
    for d in dates:
        cal = True if calibration_ok is None else bool(calibration_ok.get(d, False))
        res = sim.step(d, bars.by_date[d], sigs.by_date.get(d), cal)
        equity[d], exposure[d] = res.equity, res.exposure
        events += [f"{res.date}: {e}" for e in res.events]
    trades = pd.DataFrame([asdict(t) for t in sim.trades])
    return BacktestResult(pd.Series(equity), pd.Series(exposure), trades, events)
