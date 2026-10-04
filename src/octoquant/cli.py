"""Command line: research, backtest, paper-run, serve, review, preflight, controls, demo."""

from __future__ import annotations

import argparse
import sys
import threading
from datetime import datetime
from pathlib import Path

import joblib
import pandas as pd

from octoquant.config import Config, StrategyParams, load_config
from octoquant.data import generate_synthetic, load_panel
from octoquant.engine import BarIndex, SignalIndex, run_backtest
from octoquant.metrics import compute_metrics
from octoquant.preflight import render_preflight, run_preflight, write_preflight
from octoquant.research import calibration_gate_series, load_strategy, run_research, write_strategy_files
from octoquant.review import make_llm_client, run_nightly_review
from octoquant.runtime.notify import Notifier
from octoquant.runtime.runner import PaperRunner
from octoquant.runtime.store import Store
from octoquant.walkforward import build_dataset, fit_final_bank

DISCLAIMER = "Paper trading only. Research software, not financial advice."


def _load(args) -> Config:
    cfg = load_config(args.config)
    if args.workdir:
        wd = Path(args.workdir)
        cfg.runtime.db_path = str(wd / "octoquant.db")
        cfg.runtime.artifacts_dir = str(wd / "artifacts")
        cfg.runtime.reports_dir = str(wd / "reports")
        cfg.runtime.strategy_md = str(wd / "strategy.md")
    return cfg


def _say(msg: str) -> None:
    print(msg, flush=True)


def _banner(cfg: Config) -> None:
    if cfg.data.source == "synthetic":
        _say("NOTE: data source is SYNTHETIC. Results show the machinery works, not that an edge exists.")


def _train_and_write(ds, cfg: Config, label: str):
    res = run_research(ds, cfg, progress=_say)
    md, yml = write_strategy_files(res, cfg)
    bank, train_end = fit_final_bank(ds, cfg)
    art = Path(cfg.runtime.artifacts_dir)
    art.mkdir(parents=True, exist_ok=True)
    joblib.dump(bank, art / "bank.joblib")
    res.signals.to_pickle(art / "oos_signals.pkl.gz", compression="gzip")
    _say(f"\n{label}: strategy {'ACCEPTED' if res.accepted else 'REJECTED'} ({res.n_trials} trials)")
    for c in res.gates.checks:
        _say(f"  {c.name:20s} {c.value:9.3f}  {c.rule} {c.threshold:g}  {'pass' if c.ok else 'FAIL'}")
    _say(f"  calibration: {res.calibration.reason}")
    _say(f"wrote {md}, {yml}, model trained through {train_end.date()}")
    return res


def cmd_research(args) -> int:
    cfg = _load(args)
    _banner(cfg)
    ds = build_dataset(load_panel(cfg), cfg)
    _train_and_write(ds, cfg, "research")
    return 0


def cmd_backtest(args) -> int:
    cfg = _load(args)
    meta = load_strategy(cfg)
    sig_path = Path(cfg.runtime.artifacts_dir) / "oos_signals.pkl.gz"
    if not meta or not sig_path.exists():
        _say("no research result found: run `octoquant research` first")
        return 1
    ds = build_dataset(load_panel(cfg), cfg)
    sigs = pd.read_pickle(sig_path)
    cal = calibration_gate_series(sigs, ds.labels, cfg)
    w = meta["windows"]
    res = run_backtest(BarIndex(ds.panel.stocks), SignalIndex(sigs), StrategyParams(**meta["params"]),
                       cfg, pd.Timestamp(w["test_start"]), pd.Timestamp(w["test_end"]), cal)
    for k, v in compute_metrics(res.equity, res.trades, res.exposure).items():
        _say(f"{k:14s} {v:.4f}" if isinstance(v, float) else f"{k:14s} {v}")
    return 0


def _runner(cfg: Config) -> tuple[PaperRunner, Store, Notifier]:
    store, notifier = Store(cfg.runtime.db_path), Notifier()
    return PaperRunner(cfg, store, notifier, lambda: load_panel(cfg)), store, notifier


def cmd_paper_run(args) -> int:
    cfg = _load(args)
    runner, _, _ = _runner(cfg)
    exp = datetime.fromisoformat(args.expected_date).date() if args.expected_date else None
    out = runner.run(exp, allow_unvalidated=args.allow_unvalidated)
    _say(f"{out.status}: {out.message} equity={out.equity}")
    return 0 if out.status in ("ok", "up_to_date") else 1


def cmd_serve(args) -> int:
    import uvicorn

    from octoquant.runtime.dashboard import create_app
    from octoquant.runtime.scheduler import scheduler_loop

    cfg = _load(args)
    runner, store, notifier = _runner(cfg)
    stop = threading.Event()
    if not args.no_scheduler:
        threading.Thread(
            target=scheduler_loop, daemon=True,
            args=(lambda exp: runner.run(exp), lambda: store.get("last_attempt"),
                  lambda d: store.set("last_attempt", d), cfg, stop,
                  lambda m: (store.log_event("critical", m), notifier.send(m, "critical"))),
        ).start()
    _say(f"dashboard on http://{args.host}:{args.port}  ({DISCLAIMER})")
    uvicorn.run(create_app(cfg, store, runner), host=args.host, port=args.port, log_level="info")
    stop.set()
    return 0


def cmd_review(args) -> int:
    cfg = _load(args)
    _, store, notifier = _runner(cfg)
    sig_path = Path(cfg.runtime.artifacts_dir) / "oos_signals.pkl.gz"
    if not sig_path.exists():
        _say("no research result found: run `octoquant research` first")
        return 1
    ds = build_dataset(load_panel(cfg), cfg)
    client = make_llm_client() if args.llm else None
    if args.llm and client is None:
        _say("ANTHROPIC_API_KEY or anthropic package missing: using the deterministic reviewer")
    out = run_nightly_review(cfg, store, notifier, ds, pd.read_pickle(sig_path), client)
    _say(f"{out.status}: {out.message}")
    return 0


def cmd_preflight(args) -> int:
    cfg = _load(args)
    store = Store(cfg.runtime.db_path)
    rep = run_preflight(cfg, store, args.attest_trade_only_keys)
    path = write_preflight(rep, cfg)
    _say(render_preflight(rep))
    _say(f"report written to {path}")
    return 0 if rep.cleared else 1


def cmd_live(args) -> int:
    cfg = _load(args)
    rep = run_preflight(cfg, Store(cfg.runtime.db_path))
    _say(render_preflight(rep))
    _say("Refusing to go live: this build has no live broker adapter and the preflight is not clean.")
    return 2


def cmd_kill(args) -> int:
    cfg = _load(args)
    runner, _, _ = _runner(cfg)
    runner.set_kill_switch(not args.resume, args.reason)
    _say("kill switch cleared" if args.resume else "kill switch ON: positions flatten at the next open")
    return 0


def cmd_approve(args) -> int:
    cfg = _load(args)
    runner, _, _ = _runner(cfg)
    ok = runner.approve_held(args.order_id)
    _say("approved: fills at the next open" if ok else "no such pending order")
    return 0 if ok else 1


def cmd_demo(args) -> int:
    """End to end on synthetic data: research, then replay held-out days through the paper runner."""
    cfg = _load(args)
    if not args.workdir:
        wd = Path("demo_run")
        cfg.runtime.db_path = str(wd / "octoquant.db")
        cfg.runtime.artifacts_dir = str(wd / "artifacts")
        cfg.runtime.reports_dir = str(wd / "reports")
        cfg.runtime.strategy_md = str(wd / "strategy.md")
    _say("DEMO on SYNTHETIC data. " + DISCLAIMER)
    full = generate_synthetic(years=args.years, seed=args.seed, edge=args.edge)
    dates = full.dates
    hold = args.replay_days
    ds = build_dataset(full.truncate(dates[-hold - 1]), cfg)
    res = _train_and_write(ds, cfg, "research (data stops before the replay window)")

    store, notifier = Store(cfg.runtime.db_path), Notifier()
    runner = PaperRunner(cfg, store, notifier, lambda: full)
    _say(f"\nreplaying {hold} held-out trading days through the paper runner")
    for d in dates[-hold:]:
        runner.load_panel = lambda d=d: full.truncate(d)
        out = runner.run(d.date(), allow_unvalidated=not res.accepted)
        _say(f"  {d.date()} {out.status} equity={out.equity and round(out.equity):,} fills={out.fills}")
    rep = run_preflight(cfg, store)
    write_preflight(rep, cfg)
    _say("\n" + render_preflight(rep))
    _say(f"serve the dashboard with:  octoquant serve --workdir {Path(cfg.runtime.db_path).parent}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="octoquant", description=DISCLAIMER)
    ap.add_argument("--config", default=None, help="YAML config (default: config/default.yaml)")
    ap.add_argument("--workdir", default=None, help="redirect db, artifacts and reports here")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("research", help="walk-forward research, gates, strategy.md, model").set_defaults(fn=cmd_research)
    sub.add_parser("backtest", help="re-run the accepted strategy on its test window").set_defaults(fn=cmd_backtest)
    p = sub.add_parser("paper-run", help="one daily paper-trading cycle")
    p.add_argument("--allow-unvalidated", action="store_true")
    p.add_argument("--expected-date", default=None, help="YYYY-MM-DD; abort if data is older")
    p.set_defaults(fn=cmd_paper_run)
    p = sub.add_parser("serve", help="dashboard plus daily scheduler")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--no-scheduler", action="store_true")
    p.set_defaults(fn=cmd_serve)
    p = sub.add_parser("review", help="nightly slow-brain review")
    p.add_argument("--llm", action="store_true", help="use the Anthropic API if a key is set")
    p.set_defaults(fn=cmd_review)
    p = sub.add_parser("preflight", help="what could blow up this account?")
    p.add_argument("--attest-trade-only-keys", action="store_true")
    p.set_defaults(fn=cmd_preflight)
    sub.add_parser("live", help="refuses: no live adapter in this build").set_defaults(fn=cmd_live)
    p = sub.add_parser("kill", help="trip or clear the kill switch")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--reason", default="manual")
    p.set_defaults(fn=cmd_kill)
    p = sub.add_parser("approve", help="approve a held order")
    p.add_argument("order_id", type=int)
    p.set_defaults(fn=cmd_approve)
    p = sub.add_parser("demo", help="end-to-end run on synthetic data")
    p.add_argument("--years", type=float, default=9.0)
    p.add_argument("--seed", type=int, default=12)
    p.add_argument("--edge", type=float, default=0.003, help="planted synthetic edge (0 = none)")
    p.add_argument("--replay-days", type=int, default=30)
    p.set_defaults(fn=cmd_demo)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
