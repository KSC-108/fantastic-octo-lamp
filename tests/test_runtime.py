import copy
import logging
import shutil
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest
import yaml
from fastapi.testclient import TestClient

from octoquant.engine import BarIndex, SignalIndex, run_backtest
from octoquant.features import build_features
from octoquant.research import load_strategy
from octoquant.runtime.dashboard import create_app
from octoquant.runtime.notify import Notifier
from octoquant.runtime.runner import PaperRunner
from octoquant.runtime.scheduler import IST, is_due
from octoquant.runtime.store import Store


def replay(trained, cfg, n, start=0):
    store = Store(cfg.runtime.db_path)
    runner = PaperRunner(cfg, store, Notifier("", ""), lambda: None)
    outs = []
    for d in trained["dates"][-40:][start : start + n]:
        runner.load_panel = lambda d=d: trained["full"].truncate(d)
        outs.append(runner.run(d.date(), allow_unvalidated=True))
    return runner, store, outs


def test_refuses_without_strategy(tmp_path, trained):
    cfg = copy.deepcopy(trained["cfg"])
    cfg.runtime.artifacts_dir = str(tmp_path / "empty")
    cfg.runtime.db_path = str(tmp_path / "x.db")
    runner = PaperRunner(cfg, Store(cfg.runtime.db_path), Notifier("", ""), lambda: trained["full"])
    out = runner.run()
    assert out.status == "refused" and "research" in out.message


def test_refuses_strategy_that_failed_the_gates(tmp_path, trained):
    cfg = copy.deepcopy(trained["cfg"])
    art = tmp_path / "art"
    shutil.copytree(trained["root"] / "artifacts", art)
    meta = yaml.safe_load((art / "strategy.yaml").read_text())
    meta["accepted"] = False
    (art / "strategy.yaml").write_text(yaml.safe_dump(meta))
    cfg.runtime.artifacts_dir, cfg.runtime.db_path = str(art), str(tmp_path / "x.db")
    store = Store(cfg.runtime.db_path)
    runner = PaperRunner(cfg, store, Notifier("", ""), lambda: trained["full"])
    out = runner.run()
    assert out.status == "refused" and store.paper_days() == 0
    assert runner.run(allow_unvalidated=True).status == "ok"


def test_stale_data_aborts_and_alerts(rt_cfg, trained):
    notifier = Notifier("", "")
    store = Store(rt_cfg.runtime.db_path)
    d = trained["dates"][-40]
    runner = PaperRunner(rt_cfg, store, notifier, lambda: trained["full"].truncate(d))
    out = runner.run(expected_date=d.date() + timedelta(days=5), allow_unvalidated=True)
    assert out.status == "stale" and store.paper_days() == 0
    assert any("older than expected" in m for m in notifier.sent)


def test_replay_persists_everything_and_is_idempotent(rt_cfg, trained):
    runner, store, outs = replay(trained, rt_cfg, 12)
    assert [o.status for o in outs] == ["ok"] * 12
    assert store.paper_days() == 12
    n_sym = len(trained["full"].symbols)
    assert len(store.frame("SELECT * FROM decisions")) == 12 * n_sym
    again = runner.run(trained["dates"][-40:][11].date(), allow_unvalidated=True)
    assert again.status == "up_to_date" and store.paper_days() == 12
    sim = store.get("sim_state")
    eq = store.equity_curve().iloc[-1]
    held_value = sum(p["shares"] * p["last_close"] for p in sim["positions"].values())
    assert eq["equity"] == pytest.approx(sim["cash"] + held_value)


def test_outcomes_resolve_with_the_labelled_definition(rt_cfg, trained):
    _, store, _ = replay(trained, rt_cfg, 14)
    res = store.frame("SELECT * FROM decisions WHERE resolved=1")
    assert len(res) > 0 and set(res["y_up"].unique()) <= {0, 1}
    row = res.iloc[0]
    st, H = trained["full"].stocks, rt_cfg.model.label_horizon
    g = st[st["symbol"] == row["symbol"]].sort_values("date").reset_index(drop=True)
    i = int(g.index[g["date"] == pd.Timestamp(row["date"])][0])
    expected = g.loc[i + H, "close"] / g.loc[i + 1, "open"] - 1
    assert row["fwd_ret"] == pytest.approx(expected)
    assert int(row["fwd_ret"] > row["band"]) == row["y_up"]


def test_live_runner_matches_backtest_exactly(rt_cfg, trained):
    """Same step() in both paths: replayed equity must equal a backtest of the same days."""
    n = 15
    _, store, _ = replay(trained, rt_cfg, n)
    live = store.equity_curve().set_index("date")["equity"]
    days = trained["dates"][-40:][:n]
    from octoquant.runtime.runner import load_bank

    bank = load_bank(rt_cfg)
    feats, mkt = build_features(trained["full"])
    sig = bank.predict(feats[feats["date"].isin(days)], mkt)
    meta = load_strategy(rt_cfg)
    from octoquant.config import StrategyParams

    cal = pd.Series(bool(meta["calibration_ok"]), index=days)
    bt = run_backtest(BarIndex(trained["full"].stocks), SignalIndex(sig), StrategyParams(**meta["params"]),
                      rt_cfg, days[0], days[-1], cal)
    bt_eq = pd.Series(bt.equity.values, index=[d.strftime("%Y-%m-%d") for d in bt.equity.index])
    assert np.allclose(live.values, bt_eq.values, rtol=1e-9)


def test_kill_switch_flattens_blocks_and_can_be_cleared(rt_cfg, trained):
    runner, store, _ = replay(trained, rt_cfg, 10)
    runner.set_kill_switch(True, "drill")
    state = store.get("sim_state")
    assert state["risk"]["kill_switch"] and state["pending_entries"] == []
    d = trained["dates"][-40:][10]
    runner.load_panel = lambda: trained["full"].truncate(d)
    runner.run(d.date(), allow_unvalidated=True)
    state = store.get("sim_state")
    assert state["positions"] == {} and state["pending_entries"] == []
    assert all(r["action"] != "order" for r in store.latest_decisions().to_dict("records"))
    runner.set_kill_switch(False, "operator")
    assert not store.get("sim_state")["risk"]["kill_switch"]


def test_invalidation_trips_the_kill_switch(rt_cfg, trained):
    runner, store, _ = replay(trained, rt_cfg, 3)
    store.add_trades([{"symbol": "S00", "entry_date": "2024-01-01", "exit_date": "2024-01-02",
                       "shares": 1, "entry_px": 1.0, "exit_px": 0.9, "pnl": -1.0, "ret": -0.1,
                       "days": 1, "reason": "stop", "p_up": 0.5, "decided": "2024-01-01"}] * 60)
    meta = load_strategy(rt_cfg)
    meta["invalidation"]["hit_rate_floor"] = 0.4
    assert runner.invalidation_reasons(meta)
    d = trained["dates"][-40:][3]
    runner.load_panel = lambda: trained["full"].truncate(d)
    import octoquant.runtime.runner as mod

    orig = mod.load_strategy
    mod.load_strategy = lambda cfg, p=None: meta
    try:
        runner.run(d.date(), allow_unvalidated=True)
    finally:
        mod.load_strategy = orig
    assert store.get("sim_state")["risk"]["kill_switch"]
    assert "invalidation" in store.get("sim_state")["risk"]["kill_reason"]


def test_held_order_approval_queues_it_for_next_open(rt_cfg, trained):
    runner, store, _ = replay(trained, rt_cfg, 2)
    oid = store.add_held_order("2024-01-01", {"symbol": "S01", "notional": 50_000.0, "atr_pct": 0.02,
                                              "p_up": 0.5, "p_win": 0.6})
    assert runner.approve_held(oid)
    assert any(o["symbol"] == "S01" for o in store.get("sim_state")["pending_entries"])
    assert not runner.approve_held(oid)  # cannot approve twice


def test_dashboard_state_and_token_protected_controls(rt_cfg, trained, monkeypatch):
    runner, store, _ = replay(trained, rt_cfg, 6)
    client = TestClient(create_app(rt_cfg, store, runner))
    s = client.get("/api/state").json()
    assert s["mode"] == "PAPER" and s["equity"] and len(client.get("/api/equity").json()) == 6
    assert "OctoQuant" in client.get("/").text and client.get("/healthz").json()["ok"]
    monkeypatch.delenv("DASHBOARD_TOKEN", raising=False)
    assert client.post("/api/kill", json={}, headers={"X-Dashboard-Token": "x"}).status_code == 403
    monkeypatch.setenv("DASHBOARD_TOKEN", "secret")
    assert client.post("/api/kill", json={}).status_code == 403
    assert client.post("/api/kill", json={}, headers={"X-Dashboard-Token": "wrong"}).status_code == 403
    assert client.post("/api/kill", json={"reason": "t"}, headers={"X-Dashboard-Token": "secret"}).status_code == 200
    assert client.get("/api/state").json()["kill_switch"] is True
    assert client.post("/api/resume", headers={"X-Dashboard-Token": "secret"}).status_code == 200
    assert client.get("/api/state").json()["kill_switch"] is False


def test_notifier_never_raises_and_never_leaks_token(caplog):
    class Boom:
        def post(self, *a, **k):
            raise RuntimeError("connection to https://api.telegram.org/botSECRET123/sendMessage failed")

    n = Notifier("SECRET123", "42", client=Boom())
    with caplog.at_level(logging.WARNING):
        assert n.send("fill", "critical") is False
    assert "SECRET123" not in caplog.text and n.sent and "CRITICAL" in n.sent[0]
    assert Notifier("", "").send("x") is False


def test_store_round_trips(tmp_path):
    s = Store(tmp_path / "s.db")
    s.set("k", {"a": [1, 2]})
    assert s.get("k") == {"a": [1, 2]} and s.get("missing", 7) == 7
    s.log_event("warn", "hello")
    assert s.recent_events(1)[0]["message"] == "hello"
    mem = Store(":memory:")
    mem.set("x", 1)
    assert mem.get("x") == 1


def test_scheduler_runs_once_per_trading_day_after_cutoff():
    from octoquant.config import Config

    cfg = Config()
    cfg.runtime.holidays = ["2026-10-02"]
    at = lambda s: datetime.fromisoformat(s).replace(tzinfo=IST)  # noqa: E731
    assert not is_due(at("2026-10-03T17:00"), None, cfg)  # Saturday
    assert not is_due(at("2026-10-02T17:00"), None, cfg)  # holiday
    assert not is_due(at("2026-10-05T15:00"), None, cfg)  # before 16:10 IST
    assert is_due(at("2026-10-05T16:30"), None, cfg)
    assert not is_due(at("2026-10-05T16:30"), "2026-10-05", cfg)  # already attempted
    assert is_due(at("2026-10-06T16:30"), "2026-10-05", cfg)
    utc = datetime.fromisoformat("2026-10-05T11:00+00:00")  # 16:30 IST
    assert is_due(utc, None, cfg) and ZoneInfo("Asia/Kolkata")
