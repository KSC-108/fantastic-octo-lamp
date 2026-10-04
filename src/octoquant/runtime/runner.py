"""Paper-trading runner: one daily cycle after the NSE close.

Uses the same PortfolioSim.step() as the backtest, persists every decision with its outcome,
and refuses to run on stale data or on a strategy that has not passed the gates.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from octoquant.calibration import CalibrationReport, assess_calibration
from octoquant.config import Config, StrategyParams
from octoquant.costs import round_trip_cost_pct
from octoquant.data.base import DataPanel
from octoquant.engine import BarIndex, Order, PortfolioSim, SignalIndex
from octoquant.features import build_features, snapshot
from octoquant.research import load_strategy
from octoquant.runtime.notify import Notifier
from octoquant.runtime.report import write_daily_report
from octoquant.runtime.store import Store


@dataclass
class RunSummary:
    status: str  # ok | up_to_date | stale | refused | no_model
    message: str
    date: str | None = None
    equity: float | None = None
    fills: int = 0
    events: list[str] = field(default_factory=list)


def load_bank(cfg: Config):
    from pathlib import Path

    import joblib

    path = Path(cfg.runtime.artifacts_dir) / "bank.joblib"
    if not path.exists():
        return None
    return joblib.load(path)


class PaperRunner:
    def __init__(self, cfg: Config, store: Store, notifier: Notifier,
                 load_panel: Callable[[], DataPanel], bank=None):
        self.cfg, self.store, self.notifier = cfg, store, notifier
        self.load_panel = load_panel
        self.bank = bank

    # ---- calibration -----------------------------------------------------------------------
    def live_calibration(self, meta: dict) -> dict:
        """Live resolved decisions once there are enough; the research result until then."""
        c = self.cfg.calibration
        samples = self.store.resolved_calibration_samples(c.window_days)
        if len(samples) >= c.min_samples:
            rep: CalibrationReport = assess_calibration(
                samples["p_up"].to_numpy(float), samples["y_up"].to_numpy(float), c)
            status = {"source": "live", **rep.as_dict()}
        else:
            status = {"source": "research", "ok": bool(meta.get("calibration_ok")),
                      "ece": None, "brier": None, "n": int(len(samples)),
                      "reason": f"{len(samples)} live samples, using research calibration"}
        self.store.set("calibration", status)
        return status

    # ---- outcome resolution ----------------------------------------------------------------
    def resolve_outcomes(self, bars: BarIndex) -> int:
        H = self.cfg.model.label_horizon
        dates = bars.dates()
        pos = {d.strftime("%Y-%m-%d"): i for i, d in enumerate(dates)}
        pending = self.store.unresolved_decisions(dates[-1].strftime("%Y-%m-%d"))
        n = 0
        for r in pending.itertuples(index=False):
            i = pos.get(r.date)
            if i is None or i + H >= len(dates):
                continue
            entry = bars.by_date[dates[i + 1]].get(r.symbol)
            exit_ = bars.by_date[dates[i + H]].get(r.symbol)
            if entry is None or exit_ is None:
                continue
            fwd = exit_[3] / entry[0] - 1
            self.store.resolve_decision(r.date, r.symbol, float(fwd), int(fwd > r.band))
            n += 1
        return n

    # ---- invalidation ----------------------------------------------------------------------
    def invalidation_reasons(self, meta: dict) -> list[str]:
        inv = meta.get("invalidation", {})
        window = int(inv.get("hit_rate_window_trades", 50))
        trades = self.store.trades(window)
        if len(trades) >= window:
            hit = float((trades["pnl"] > 0).mean())
            floor = float(inv.get("hit_rate_floor", 0.0))
            if hit < floor:
                return [f"hit rate {hit:.0%} over last {window} trades is below floor {floor:.0%}"]
        return []

    # ---- the cycle -------------------------------------------------------------------------
    def run(self, expected_date: date | None = None, allow_unvalidated: bool = False) -> RunSummary:
        cfg, store = self.cfg, self.store
        meta = load_strategy(cfg)
        if meta is None:
            return self._alert_summary("refused", "no strategy.yaml: run `octoquant research` first",
                                       "critical")
        if not meta.get("accepted") and not allow_unvalidated:
            return self._alert_summary(
                "refused", "strategy did not pass the acceptance gates; refusing to trade", "critical")
        bank = self.bank or load_bank(cfg)
        if bank is None:
            return self._alert_summary("no_model", "no trained model: run `octoquant research`",
                                       "critical")
        params = StrategyParams(**meta["params"])

        panel = self.load_panel()
        dates = panel.dates
        target = dates[-1]
        if expected_date and target.date() < expected_date:
            return self._alert_summary(
                "stale", f"latest bar {target.date()} is older than expected {expected_date}", "critical")

        last = store.get("last_date")
        state = store.get("sim_state")
        sim = (PortfolioSim.from_dict(state, cfg, params) if state
               else PortfolioSim(params, cfg.costs, cfg.risk, cfg.sizing, cfg.runtime.initial_equity))
        sim.params = params
        if last and target.strftime("%Y-%m-%d") <= last:
            return RunSummary("up_to_date", f"already processed {last}", last)
        todo = [target] if not last else [d for d in dates if d > pd.Timestamp(last)]

        feats, mkt = build_features(panel)
        bars = BarIndex(panel.stocks)
        rt = round_trip_cost_pct(cfg.costs)
        summary = RunSummary("ok", "", None)
        for d in todo:
            started = time.perf_counter()
            rows = feats[feats["date"] == d]
            sig_df = bank.predict(rows, mkt)
            latency_ms = (time.perf_counter() - started) * 1000 / max(len(sig_df), 1)
            store.set("latency_ms", latency_ms)
            sigs = SignalIndex(sig_df).by_date[d]
            cal = self.live_calibration(meta)

            held: list[Order] = []

            def approve(order: Order, _h=held) -> bool:
                _h.append(order)
                return False

            n_trades = len(sim.trades)
            res = sim.step(d, bars.by_date[d], sigs, cal["ok"], approve, record_decisions=True)
            vol = dict(zip(sig_df["symbol"], sig_df["vol_20"], strict=True))
            bands = {s: cfg.model.band_k * v * np.sqrt(cfg.model.label_horizon) + rt
                     for s, v in vol.items() if np.isfinite(v)}
            snaps = {r["symbol"]: snapshot(feats, d, r["symbol"]) for r in res.decisions if r["fired"]}
            store.add_decisions(res.date, res.decisions, bands, snaps)
            if res.fills:
                store.add_fills(res.fills)
            if len(sim.trades) > n_trades:
                store.add_trades([asdict(t) for t in sim.trades[n_trades:]])
            peak = sim.risk.state.peak_equity
            store.add_equity(res.date, res.equity, res.cash, res.exposure, 1 - res.equity / peak)

            for f in res.fills:
                self.notifier.send(f"{f['side'].upper()} {f['shares']} {f['symbol']} @ "
                                   f"{f['price']:.2f} ({f['reason']})")
            for o in held:
                oid = store.add_held_order(res.date, asdict(o))
                self.notifier.send(f"order #{oid} {o.symbol} Rs {o.notional:,.0f} needs manual "
                                   "approval", "warn")
            for e in res.events:
                level = "critical" if "KILL SWITCH" in e else "warn"
                store.log_event(level, e)
                self.notifier.send(e, level)
            if not cal["ok"]:
                store.log_event("warn", f"calibration gate failing: {cal['reason']}")
            summary = RunSummary("ok", f"processed {res.date}", res.date, res.equity,
                                 summary.fills + len(res.fills), summary.events + res.events)

        reasons = self.invalidation_reasons(meta)
        if reasons and not sim.risk.state.kill_switch:
            sim.risk.trip("invalidation: " + "; ".join(reasons))
            store.log_event("critical", sim.risk.state.kill_reason)
            self.notifier.send(sim.risk.state.kill_reason, "critical")
        store.set("sim_state", sim.to_dict())
        store.set("last_date", todo[-1].strftime("%Y-%m-%d"))
        resolved = self.resolve_outcomes(bars)
        store.set("last_run", {"date": summary.date, "resolved": resolved})
        write_daily_report(cfg, store, summary.date)
        return summary

    def _alert_summary(self, status: str, message: str, level: str) -> RunSummary:
        self.store.log_event(level, message)
        self.notifier.send(message, level)
        return RunSummary(status, message)

    # ---- human controls --------------------------------------------------------------------
    def approve_held(self, order_id: int) -> bool:
        held = self.store.frame("SELECT * FROM held_orders WHERE id=? AND status='pending'",
                                (order_id,))
        state = self.store.get("sim_state")
        if held.empty or not state:
            return False
        r = held.iloc[0]
        state["pending_entries"].append({
            "symbol": r["symbol"], "notional": float(r["notional"]), "atr_pct": float(r["atr_pct"]),
            "p_up": float(r["p_up"]), "p_win": float(r["p_win"]), "decided": str(r["date"])})
        self.store.set("sim_state", state)
        self.store.set_held_status(order_id, "approved")
        return True

    def set_kill_switch(self, on: bool, reason: str = "manual") -> None:
        state = self.store.get("sim_state")
        if not state:
            raise RuntimeError("no simulator state yet: run the daily job once first")
        risk = state["risk"]
        if on:
            risk["kill_switch"], risk["kill_reason"] = True, reason
            for sym in state["positions"]:
                state["pending_exits"][sym] = "kill switch"
            state["pending_entries"] = []
        else:
            risk["kill_switch"], risk["kill_reason"] = False, ""
            risk["peak_equity"] = risk["prev_equity"]
        self.store.set("sim_state", state)
        self.store.log_event("critical" if on else "warn",
                             f"kill switch {'ON' if on else 'cleared'} ({reason})")
        self.notifier.send(f"kill switch {'ON' if on else 'cleared'}: {reason}",
                           "critical" if on else "warn")
