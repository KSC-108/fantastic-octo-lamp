"""Options paper book: the backtest simulator stepped once per trading day on live data.

The book keeps its own capital, positions, kill switch and logs, separate from the equity book.
Manual tickets go through the same sizing and margin checks and fill at the next open.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

from octoquant.config import Config
from octoquant.options.chain import OptionChain
from octoquant.options.engine import OptionsSimulator, SimState
from octoquant.options.strategies import STRATEGIES, payoff_curve, payoff_extremes
from octoquant.runtime.notify import Notifier
from octoquant.runtime.store import Store

STATE_KEY = "opt_sim_state"
BACKTEST_KEY = "opt_backtest"


@dataclass
class OptionsRunOutcome:
    status: str
    message: str
    equity: float | None = None
    fills: int = 0


class OptionsPaperBook:
    def __init__(self, cfg: Config, store: Store, notifier: Notifier,
                 load_chain: Callable[[], OptionChain]):
        self.cfg, self.store, self.notifier, self.load_chain = cfg, store, notifier, load_chain

    def _sim(self) -> OptionsSimulator:
        raw = self.store.get(STATE_KEY)
        return OptionsSimulator(self.cfg, SimState.from_dict(raw) if raw else None)

    def _save(self, sim: OptionsSimulator) -> None:
        self.store.set(STATE_KEY, sim.state.to_dict())

    def _accepted(self) -> bool:
        bt = self.store.get(BACKTEST_KEY) or {}
        name = self.cfg.options.strategy.name
        return any(r.get("strategy") == name and r.get("accepted") for r in bt.get("results", []))

    def run(self, allow_unvalidated: bool = False) -> OptionsRunOutcome:
        """Step every trading day after the last processed one, in order."""
        if not allow_unvalidated and not self._accepted():
            return OptionsRunOutcome("refused", f"strategy {self.cfg.options.strategy.name} has not passed "
                                     "the gates in `octoquant options backtest`; use --allow-unvalidated to paper "
                                     "trade it anyway")
        chain = self.load_chain()
        sim = self._sim()
        last = pd.Timestamp(sim.state.last_date) if sim.state.last_date else None
        todo = [d for d in chain.dates if last is None or d > last]
        if last is None:
            todo = todo[-1:]  # a new book starts today, not at the start of history
        if not todo:
            return OptionsRunOutcome("up_to_date", f"already processed {sim.state.last_date}", sim.equity())
        n_fills = 0
        for d in todo:
            rep = sim.step(d, chain.truncate(d))
            row = rep.row()
            row["positions"] = len(sim.state.positions)
            self.store.insert_rows("opt_daily", [row])
            self.store.insert_rows("opt_fills", rep.fills)
            self.store.insert_rows("opt_trades", rep.trades)
            n_fills += len(rep.fills)
            for lvl, msg in rep.events:
                if lvl != "info":  # routine rule decisions stay out of the shared event log
                    self.store.log_event(lvl, f"[options] {msg}")
                    self.notifier.send(f"[options] {msg}", lvl)
            for t in rep.trades:
                self.notifier.send(f"[options] closed {t['strategy']} exp {t['expiry']} "
                                   f"({t['reason']}): P&L Rs {t['pnl']:,.0f}", "info")
        self._save(sim)
        return OptionsRunOutcome("ok", f"processed {len(todo)} day(s) through {sim.state.last_date}",
                                 sim.equity(), n_fills)

    # -- manual tickets --
    def ticket(self, strategy: str, expiry: str | None, lots: int, width: int | None = None,
               wing: int | None = None) -> tuple[bool, str]:
        if strategy not in STRATEGIES:
            return False, f"unknown strategy {strategy}; choose from {', '.join(STRATEGIES)}"
        chain = self.load_chain()
        sim = self._sim()
        if sim.state.kill_switch:
            return False, "options kill switch is on"
        date = chain.dates.max()
        if sim.state.last_date and str(date.date()) != sim.state.last_date:
            return False, (f"book is at {sim.state.last_date} but data ends {date.date()}: run "
                           "`octoquant options paper-run` first so the ticket is priced on the book's day")
        exps = [e for e in chain.expiries(date) if (e - date).days >= self.cfg.options.strategy.min_dte]
        exp = pd.Timestamp(expiry) if expiry else (exps[0] if exps else None)
        if exp is None or exp not in exps:
            return False, f"expiry must be one of {[str(e.date()) for e in exps]}"
        ok, msg = sim.queue_entry(chain, date, exp, strategy, lots, width, wing, source="manual")
        if ok:
            if sim.state.last_date is None:
                sim.state.last_date = str(date.date())
            self._save(sim)
            self.store.log_event("info", f"[options] manual ticket: {msg}")
        return ok, msg

    def close(self, position_id: int) -> bool:
        sim = self._sim()
        ok = sim.queue_exit(position_id, "manual close")
        if ok:
            self._save(sim)
            self.store.log_event("info", f"[options] manual close queued for position {position_id}")
        return ok

    def set_kill_switch(self, on: bool, reason: str = "manual") -> None:
        sim = self._sim()
        sim.set_kill_switch(on, reason)
        self._save(sim)
        self.store.log_event("critical" if on else "info",
                             f"[options] kill switch {'ON' if on else 'cleared'}: {reason}")

    # -- views --
    def state_view(self) -> dict:
        sim = self._sim()
        positions = sim.position_view()
        for p in positions:
            legs = [{"kind": x["kind"], "side": x["side"], "strike": x["strike"], "premium": x["entry_px"]}
                    for x in p["legs"]]
            p["payoff"] = payoff_points(legs, sim.o.lot_size * p["lots"])
        daily = self.store.frame("SELECT * FROM opt_daily ORDER BY date")
        last = daily.iloc[-1].to_dict() if len(daily) else {}
        return {"as_of": sim.state.last_date, "equity": last.get("equity", sim.equity()),
                "drawdown": last.get("drawdown"), "margin": last.get("margin"), "spot": last.get("spot"),
                "atm_iv": last.get("atm_iv"),
                "greeks": {k: last.get(k) for k in ("delta", "gamma", "vega", "theta")},
                "kill_switch": sim.state.kill_switch, "kill_reason": sim.state.kill_reason,
                "strategy": sim.params.name, "positions": positions,
                "pending": [{"strategy": e.strategy, "expiry": e.expiry, "lots": e.lots, "source": e.source,
                             "decided": e.decided, "legs": [{"kind": x.kind, "side": x.side,
                                                             "strike": x.strike} for x in e.legs]}
                            for e in sim.state.pending_entries]}


def payoff_points(legs: list[dict], qty: int, n: int = 121) -> dict:
    """Expiry payoff in rupees across a price range around the strikes, for charting."""
    import numpy as np

    ks = [x["strike"] for x in legs]
    lo, hi = min(ks), max(ks)
    pad = max((hi - lo) * 0.6, lo * 0.03)
    s = np.linspace(lo - pad, hi + pad, n)
    pnl = payoff_curve(legs, s) * qty
    mp, ml, bes = payoff_extremes(legs, (lo + hi) / 2)
    return {"s": [round(float(x), 2) for x in s], "pnl": [round(float(x), 2) for x in pnl],
            "breakevens": [round(b, 2) for b in bes],
            "max_profit": mp * qty if np.isfinite(mp) else None,
            "max_loss": ml * qty if np.isfinite(ml) else None}
