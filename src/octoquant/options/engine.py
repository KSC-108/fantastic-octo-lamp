"""Options simulator. One `step()` per trading day, shared by the backtest and the paper book.

Timing, chosen so nothing is seen before it is known:
- Decisions (entries, stops, targets, DTE exits) use prices at the close of day t.
- Orders fill at the open of day t+1 with slippage. Bhavcopy files carry an option open price;
  the model chain prices the open from the underlying's open and the previous close's volatility.
- Positions still open on expiry day settle at intrinsic value against the underlying's close
  (NSE index options are European and cash-settled). Exercised long legs pay STT on intrinsic.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from octoquant.config import Config, OptionCostConfig, OptionStrategyParams
from octoquant.metrics import GateResult, compute_metrics, evaluate_gates
from octoquant.options.chain import OptionChain, year_frac
from octoquant.options.pricing import bs_greeks
from octoquant.options.strategies import STRATEGIES, payoff_extremes

IV_HISTORY = 252
MIN_IV_HISTORY = 60


# ---- costs --------------------------------------------------------------------------------------
def option_fill_price(px: float, side: int, c: OptionCostConfig) -> float:
    slip = max(px * c.slippage_pct, c.min_slippage)
    return px + slip if side > 0 else max(px - slip, 0.05)


def option_fees(px: float, side: int, qty: int, c: OptionCostConfig) -> float:
    """Rupee charges for one leg fill. side +1 buy, -1 sell."""
    prem = px * qty
    brokerage = c.brokerage_per_order
    txn = c.exchange_txn_pct * prem
    sebi = c.sebi_pct * prem
    stt = c.stt_sell_premium_pct * prem if side < 0 else 0.0
    stamp = c.stamp_buy_pct * prem if side > 0 else 0.0
    return brokerage + txn + sebi + stt + stamp + c.gst_pct * (brokerage + txn + sebi)


# ---- state --------------------------------------------------------------------------------------
@dataclass
class OptLeg:
    kind: str
    strike: float
    side: int
    entry_px: float = 0.0
    mark: float = 0.0


@dataclass
class OptPosition:
    id: int
    strategy: str
    expiry: str
    lots: int
    legs: list[OptLeg]
    entry_date: str
    decided: str
    entry_costs: float
    credit: float          # net premium per unit at fill; positive = received
    margin: float          # rupees blocked
    max_loss: float | None # rupees, None = undefined risk
    max_profit: float | None
    source: str = "rule"

    @property
    def is_credit(self) -> bool:
        return self.credit > 0


@dataclass
class PendingEntry:
    strategy: str
    expiry: str
    legs: list[OptLeg]
    lots: int
    decided: str
    margin_per_lot: float
    source: str = "rule"


@dataclass
class SimState:
    cash: float
    peak: float
    positions: dict[int, OptPosition] = field(default_factory=dict)
    pending_entries: list[PendingEntry] = field(default_factory=list)
    pending_exits: dict[int, str] = field(default_factory=dict)
    entered_expiries: list[str] = field(default_factory=list)
    iv_hist: list[float] = field(default_factory=list)
    kill_switch: bool = False
    kill_reason: str = ""
    last_date: str | None = None
    next_id: int = 1

    def to_dict(self) -> dict:
        d = asdict(self)
        d["positions"] = {str(k): v for k, v in d["positions"].items()}
        d["pending_exits"] = {str(k): v for k, v in self.pending_exits.items()}
        return d

    @classmethod
    def from_dict(cls, d: dict) -> SimState:
        s = cls(cash=d["cash"], peak=d["peak"])
        s.positions = {int(k): OptPosition(**{**p, "legs": [OptLeg(**x) for x in p["legs"]]})
                       for k, p in d["positions"].items()}
        s.pending_entries = [PendingEntry(**{**p, "legs": [OptLeg(**x) for x in p["legs"]]})
                             for p in d["pending_entries"]]
        s.pending_exits = {int(k): v for k, v in d["pending_exits"].items()}
        for k in ("entered_expiries", "iv_hist", "kill_switch", "kill_reason", "last_date", "next_id"):
            setattr(s, k, d[k])
        return s


@dataclass
class StepReport:
    date: str
    equity: float
    cash: float
    margin: float
    drawdown: float
    greeks: dict
    spot: float
    atm_iv: float | None
    fills: list[dict] = field(default_factory=list)
    trades: list[dict] = field(default_factory=list)
    events: list[tuple[str, str]] = field(default_factory=list)

    def row(self) -> dict:
        return {"date": self.date, "equity": self.equity, "cash": self.cash, "margin": self.margin,
                "exposure": self.margin / self.equity if self.equity > 0 else 0.0,
                "drawdown": self.drawdown, "spot": self.spot, "atm_iv": self.atm_iv,
                "positions": None, **self.greeks}


# ---- simulator ----------------------------------------------------------------------------------
class OptionsSimulator:
    def __init__(self, cfg: Config, state: SimState | None = None,
                 params: OptionStrategyParams | None = None):
        self.cfg = cfg
        self.o = cfg.options
        self.params = params or self.o.strategy
        self.state = state or SimState(cash=self.o.risk.initial_capital, peak=self.o.risk.initial_capital)

    # -- helpers --
    @property
    def lot(self) -> int:
        return self.o.lot_size

    def _qty(self, lots: int) -> int:
        return lots * self.lot

    def equity(self) -> float:
        held = sum(leg.side * leg.mark * self._qty(p.lots) for p in self.state.positions.values()
                   for leg in p.legs)
        return self.state.cash + held

    def margin_used(self) -> float:
        used = sum(p.margin for p in self.state.positions.values())
        return used + sum(e.margin_per_lot * e.lots for e in self.state.pending_entries)

    def build_legs(self, chain: OptionChain, date: pd.Timestamp, expiry: pd.Timestamp,
                   strategy: str, width: int, wing: int) -> list[OptLeg] | None:
        spec = STRATEGIES[strategy]
        step = self.o.strike_step
        atm = chain.nearest_strike(date, expiry, chain.spot(date))
        if atm is None:
            return None
        legs = []
        for kind, side, steps in spec.offsets(width, wing):
            target = atm + steps * step
            k = chain.nearest_strike(date, expiry, target)
            if k is None or abs(k - target) > step / 2 + 1e-9:
                return None
            px = chain.price(date, expiry, k, kind)
            if px is None:
                return None
            legs.append(OptLeg(kind, k, side, entry_px=px, mark=px))
        return legs

    def size(self, legs: list[OptLeg], spot: float, equity: float, strategy: str) -> dict:
        """Per-lot risk and margin, and the lot count the risk limits allow."""
        r, p = self.o.risk, self.params
        unit = [{"kind": x.kind, "side": x.side, "strike": x.strike, "premium": x.entry_px} for x in legs]
        max_profit, max_loss, bes = payoff_extremes(unit, spot)
        credit = -sum(x.side * x.entry_px for x in legs)
        if math.isfinite(max_loss):
            risk_lot = max_loss * self.lot
            margin_lot = risk_lot if credit > 0 else max(-credit, 0.0) * self.lot
        else:
            risk_lot = p.stop_loss_mult * max(credit, 0.0) * self.lot
            shorts = max(sum(1 for x in legs if x.side < 0 and x.kind == k) for k in ("CE", "PE"))
            margin_lot = r.naked_margin_pct * spot * self.lot * shorts
        risk_lot, margin_lot = max(risk_lot, 1.0), max(margin_lot, 1.0)
        room = r.max_margin_pct * equity - self.margin_used()
        lots = min(r.max_lots, int(r.risk_per_trade_pct * equity // risk_lot), int(max(room, 0) // margin_lot))
        return {"lots": max(lots, 0), "risk_lot": risk_lot, "margin_lot": margin_lot, "credit": credit,
                "max_profit": max_profit, "max_loss": max_loss, "breakevens": bes, "defined": math.isfinite(max_loss)}

    def iv_rank(self, iv: float | None) -> float | None:
        h = self.state.iv_hist
        if iv is None or len(h) < MIN_IV_HISTORY:
            return None
        return float(np.mean(np.asarray(h) < iv))

    # -- orders --
    def queue_entry(self, chain, date, expiry, strategy, lots=None, width=None, wing=None,
                    source="rule") -> tuple[bool, str]:
        p = self.params
        width = p.width_steps if width is None else width
        wing = p.wing_steps if wing is None else wing
        legs = self.build_legs(chain, date, expiry, strategy, width, wing)
        if legs is None:
            return False, f"{strategy} {expiry.date()}: strikes or prices missing"
        sz = self.size(legs, chain.spot(date), self.equity(), strategy)
        floor = 2 * len(legs) * self.o.costs.min_slippage
        if STRATEGIES[strategy].credit and sz["credit"] <= floor:
            return False, f"{strategy} {expiry.date()}: credit {sz['credit']:.2f} does not cover slippage"
        if not STRATEGIES[strategy].credit and -sz["credit"] <= floor:
            return False, f"{strategy} {expiry.date()}: debit {-sz['credit']:.2f} too small to trade"
        want = sz["lots"] if lots is None else int(lots)
        if want < 1 or (lots is not None and want > sz["lots"]):
            return False, (f"{strategy} {expiry.date()}: risk limits allow {sz['lots']} lot(s) "
                           f"(risk/lot Rs {sz['risk_lot']:,.0f}, margin/lot Rs {sz['margin_lot']:,.0f})")
        self.state.pending_entries.append(PendingEntry(
            strategy, str(expiry.date()), legs, want, str(date.date()), sz["margin_lot"], source))
        return True, f"queued {want} lot(s) {strategy} exp {expiry.date()} for the next open"

    def queue_exit(self, pos_id: int, reason: str) -> bool:
        if pos_id in self.state.positions and pos_id not in self.state.pending_exits:
            self.state.pending_exits[pos_id] = reason
            return True
        return False

    def set_kill_switch(self, on: bool, reason: str = "") -> None:
        self.state.kill_switch, self.state.kill_reason = on, reason
        if on:
            for pid in list(self.state.positions):
                self.queue_exit(pid, "kill switch")
            self.state.pending_entries.clear()

    # -- the daily step --
    def step(self, date: pd.Timestamp, chain: OptionChain, decide: bool = True) -> StepReport:
        st, c, ds = self.state, self.o.costs, str(date.date())
        fills, trades, events = [], [], []

        # 1. exits queued yesterday fill at today's open
        for pid, reason in list(st.pending_exits.items()):
            pos = st.positions.get(pid)
            if pos is None:
                continue
            exp = pd.Timestamp(pos.expiry)
            if exp < date:
                continue  # settles below
            proceeds, fees = 0.0, 0.0
            for leg in pos.legs:
                px = chain.price(date, exp, leg.strike, leg.kind, at_open=True)
                px = leg.mark if px is None else px
                fpx = option_fill_price(px, -leg.side, c)
                q = self._qty(pos.lots)
                proceeds += leg.side * fpx * q
                fees += option_fees(fpx, -leg.side, q, c)
                fills.append(self._fill(ds, pos, leg, -leg.side, fpx, reason))
            st.cash += proceeds - fees
            trades.append(self._close(pos, ds, proceeds, fees, reason))
            del st.pending_exits[pid]

        # 2. entries queued yesterday fill at today's open
        for e in st.pending_entries:
            exp = pd.Timestamp(e.expiry)
            if st.kill_switch or exp < date:
                continue
            pxs = [chain.price(date, exp, leg.strike, leg.kind, at_open=True) for leg in e.legs]
            if any(px is None for px in pxs):
                events.append(("warn", f"entry {e.strategy} {e.expiry} cancelled: no open price"))
                continue
            q, fees, legs = self._qty(e.lots), 0.0, []
            for leg, px in zip(e.legs, pxs, strict=True):
                fpx = option_fill_price(px, leg.side, c)
                st.cash -= leg.side * fpx * q
                fees += option_fees(fpx, leg.side, q, c)
                legs.append(OptLeg(leg.kind, leg.strike, leg.side, fpx, fpx))
            st.cash -= fees
            unit = [{"kind": x.kind, "side": x.side, "strike": x.strike, "premium": x.entry_px} for x in legs]
            mp, ml, _ = payoff_extremes(unit, chain.spot(date, at_open=True))
            pos = OptPosition(st.next_id, e.strategy, e.expiry, e.lots, legs, ds, e.decided, fees,
                              -sum(x.side * x.entry_px for x in legs), e.margin_per_lot * e.lots,
                              ml * q if math.isfinite(ml) else None,
                              mp * q if math.isfinite(mp) else None, e.source)
            st.positions[pos.id] = pos
            st.next_id += 1
            for leg in legs:
                fills.append(self._fill(ds, pos, leg, leg.side, leg.entry_px, "entry"))
        st.pending_entries = []

        # 3. mark to the close; settle anything at or past expiry
        spot = chain.spot(date)
        for pid, pos in list(st.positions.items()):
            exp = pd.Timestamp(pos.expiry)
            if exp <= date:
                settle_day = max(d for d in chain.dates if d <= exp) if exp < date else date
                s = chain.spot(settle_day)
                value, stt = 0.0, 0.0
                q = self._qty(pos.lots)
                for leg in pos.legs:
                    intrinsic = max(s - leg.strike, 0.0) if leg.kind == "CE" else max(leg.strike - s, 0.0)
                    leg.mark = intrinsic
                    value += leg.side * intrinsic * q
                    if leg.side > 0 and intrinsic > 0:
                        stt += c.stt_exercise_pct * intrinsic * q
                st.cash += value - stt
                trades.append(self._close(pos, ds, value, stt, "expiry"))
                st.pending_exits.pop(pid, None)
                continue
            for leg in pos.legs:
                px = chain.price(date, exp, leg.strike, leg.kind)
                if px is not None:
                    leg.mark = px

        # 4. equity, drawdown, kill switch
        eq = self.equity()
        st.peak = max(st.peak, eq)
        dd = 1 - eq / st.peak if st.peak > 0 else 0.0
        if dd >= self.o.risk.max_drawdown_pct and not st.kill_switch:
            self.set_kill_switch(True, f"drawdown {dd:.1%} >= {self.o.risk.max_drawdown_pct:.0%}")
            events.append(("critical", f"options kill switch: {st.kill_reason}"))

        # 5. exit rules at the close (fill tomorrow)
        p = self.params
        for pid, pos in st.positions.items():
            if pid in st.pending_exits:
                continue
            pnl_unit = sum(leg.side * (leg.mark - leg.entry_px) for leg in pos.legs)
            dte = (pd.Timestamp(pos.expiry) - date).days
            q = self._qty(pos.lots)
            if pos.is_credit:
                stop = pnl_unit <= -p.stop_loss_mult * pos.credit
                target_base = pos.credit if pos.max_profit is None else min(pos.credit, pos.max_profit / q)
            else:
                debit = -pos.credit
                stop = pnl_unit <= -p.debit_stop_pct * debit
                target_base = debit if pos.max_profit is None else pos.max_profit / q
            if stop:
                self.queue_exit(pid, "stop loss")
            elif pnl_unit >= p.take_profit_pct * target_base > 0:
                self.queue_exit(pid, "take profit")
            elif p.exit_dte > 0 and dte <= p.exit_dte:
                self.queue_exit(pid, f"DTE <= {p.exit_dte}")

        # 6. IV history and new entries
        atm_iv = chain.atm_iv(date)
        rank = self.iv_rank(atm_iv)
        if atm_iv is not None:
            st.iv_hist = (st.iv_hist + [atm_iv])[-IV_HISTORY:]
        if decide and not st.kill_switch:
            events += self._decide(chain, date, rank)

        st.last_date = ds
        rep = StepReport(ds, eq, st.cash, sum(x.margin for x in st.positions.values()), dd,
                         self.book_greeks(chain, date), spot, atm_iv, fills, trades, events)
        return rep

    def _decide(self, chain, date, rank) -> list[tuple[str, str]]:
        p, st = self.params, self.state
        spec = STRATEGIES[p.name]
        if len(st.positions) + len(st.pending_entries) - len(st.pending_exits) >= self.o.risk.max_open_positions:
            return []
        cands = [e for e in chain.expiries(date)
                 if p.min_dte <= (e - date).days <= p.entry_dte and str(e.date()) not in st.entered_expiries]
        if not cands:
            return []
        selling = spec.credit
        if p.min_iv_rank is not None and selling and (rank is None or rank < p.min_iv_rank):
            return []
        if p.max_iv_rank is not None and not selling and (rank is None or rank > p.max_iv_rank):
            return []
        ok, msg = self.queue_entry(chain, date, cands[0], p.name)
        if ok:
            st.entered_expiries = (st.entered_expiries + [str(cands[0].date())])[-60:]
            return [("info", msg)]
        return [("info", f"no entry: {msg}")]

    def book_greeks(self, chain, date) -> dict:
        out = {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0}
        if not self.state.positions:
            return out
        s = chain.spot(date)
        for pos in self.state.positions.values():
            exp = pd.Timestamp(pos.expiry)
            t = year_frac(date, exp)
            q = self._qty(pos.lots)
            for leg in pos.legs:
                iv = chain.iv(date, exp, leg.strike, leg.kind) if t > 0 else None
                g = bs_greeks(s, leg.strike, t, iv or 0.0, leg.kind, self.o.risk_free, self.o.dividend_yield)
                for k in out:
                    out[k] += leg.side * q * g[k]
        return out

    def _fill(self, ds, pos, leg, side, px, reason) -> dict:
        return {"date": ds, "position_id": pos.id, "strategy": pos.strategy, "expiry": pos.expiry,
                "kind": leg.kind, "strike": leg.strike, "side": "buy" if side > 0 else "sell",
                "qty": self._qty(pos.lots), "price": round(px, 2), "reason": reason}

    def _close(self, pos: OptPosition, ds: str, proceeds: float, fees: float, reason: str) -> dict:
        q = self._qty(pos.lots)
        opened = -pos.credit * q  # rupees paid at entry (negative when credit received)
        pnl = proceeds - opened - fees - pos.entry_costs
        del self.state.positions[pos.id]
        return {"position_id": pos.id, "strategy": pos.strategy, "expiry": pos.expiry,
                "entry_date": pos.entry_date, "exit_date": ds, "lots": pos.lots,
                "credit": round(pos.credit, 2), "exit_value": round(proceeds / q, 2),
                "pnl": pnl, "ret": pnl / max(pos.margin, 1.0), "costs": fees + pos.entry_costs,
                "days": (pd.Timestamp(ds) - pd.Timestamp(pos.entry_date)).days,
                "reason": reason, "source": pos.source}

    def position_view(self) -> list[dict]:
        out = []
        for pos in self.state.positions.values():
            q = self._qty(pos.lots)
            pnl = sum(leg.side * (leg.mark - leg.entry_px) for leg in pos.legs) * q - pos.entry_costs
            out.append({"id": pos.id, "strategy": pos.strategy, "label": STRATEGIES[pos.strategy].label,
                        "expiry": pos.expiry, "lots": pos.lots, "entry_date": pos.entry_date,
                        "credit": pos.credit, "margin": pos.margin, "max_loss": pos.max_loss,
                        "max_profit": pos.max_profit, "pnl": pnl, "source": pos.source,
                        "exit_pending": self.state.pending_exits.get(pos.id),
                        "legs": [asdict(x) for x in pos.legs]})
        return out


# ---- backtest -----------------------------------------------------------------------------------
@dataclass
class OptionsBacktestResult:
    strategy: str
    daily: pd.DataFrame
    trades: pd.DataFrame
    metrics: dict
    gates: GateResult
    chain: str
    vol_source: str
    params: dict
    events: list = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return self.gates.passed

    def summary(self) -> dict:
        m = self.metrics
        return {"strategy": self.strategy, "label": STRATEGIES[self.strategy].label,
                "accepted": self.accepted, "chain": self.chain, "vol_source": self.vol_source,
                "start": str(self.daily["date"].iloc[0]) if len(self.daily) else None,
                "end": str(self.daily["date"].iloc[-1]) if len(self.daily) else None,
                **{k: _num(m.get(k)) for k in ("total_return", "cagr", "sharpe", "max_drawdown",
                                                "hit_rate", "n_trades", "profit_factor", "tstat")},
                "avg_pnl": _num(self.trades["pnl"].mean()) if len(self.trades) else None,
                "worst_trade": _num(self.trades["pnl"].min()) if len(self.trades) else None,
                "costs": _num(self.trades["costs"].sum()) if len(self.trades) else 0.0,
                "gates": [c.as_dict() for c in self.gates.checks]}


def _num(v):
    if v is None:
        return None
    v = float(v)
    return v if math.isfinite(v) else None


def simple_regimes(spot: pd.Series, lookback: int = 60, band: float = 0.04) -> pd.Series:
    """Trailing-return regime label for gate coverage: 0 bull, 1 chop, 2 bear."""
    r = spot / spot.shift(lookback) - 1
    return pd.Series(np.where(r > band, 0, np.where(r < -band, 2, 1)), index=spot.index).where(r.notna())


def run_options_backtest(chain: OptionChain, cfg: Config, params: OptionStrategyParams | None = None,
                         start: pd.Timestamp | None = None, end: pd.Timestamp | None = None
                         ) -> OptionsBacktestResult:
    sim = OptionsSimulator(cfg, params=params)
    dates = [d for d in chain.dates if (start is None or d >= start) and (end is None or d <= end)]
    rows, trades, events = [], [], []
    for d in dates:
        rep = sim.step(d, chain)
        row = rep.row()
        row["positions"] = len(sim.state.positions)
        rows.append(row)
        trades += rep.trades
        events += [(rep.date, lvl, msg) for lvl, msg in rep.events if lvl != "info"]
    daily = pd.DataFrame(rows)
    tr = pd.DataFrame(trades, columns=["position_id", "strategy", "expiry", "entry_date", "exit_date",
                                       "lots", "credit", "exit_value", "pnl", "ret", "costs", "days",
                                       "reason", "source"])
    eq = daily.set_index(pd.to_datetime(daily["date"]))["equity"] if len(daily) else pd.Series(dtype=float)
    m = compute_metrics(eq, tr, daily["exposure"] if len(daily) else None)
    spot = daily.set_index(pd.to_datetime(daily["date"]))["spot"] if len(daily) else pd.Series(dtype=float)
    shares = {}
    if len(spot):
        reg = simple_regimes(spot).dropna()
        shares = {int(k): float(v) for k, v in reg.value_counts(normalize=True).items()}
    gates = evaluate_gates(m, cfg.gates, shares)
    p = sim.params
    return OptionsBacktestResult(p.name, daily, tr, m, gates, chain.name,
                                 getattr(chain, "vol_source", getattr(chain, "spot_source", "")),
                                 p.model_dump(), events)
