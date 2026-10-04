import numpy as np
import pandas as pd
import pytest

from octoquant.config import Config, CostConfig, GatesConfig, RiskConfig, SizingConfig, StrategyParams
from octoquant.engine import PortfolioSim
from octoquant.metrics import compute_metrics, evaluate_gates
from octoquant.sizing import kelly_fraction, position_fraction

ZERO = CostConfig(brokerage_pct=0, stt_pct=0, exchange_txn_pct=0, sebi_pct=0, stamp_buy_pct=0,
                  gst_pct=0, dp_charge_sell=0, slippage_bps=0)
D = [pd.Timestamp("2024-01-01") + pd.Timedelta(days=i) for i in range(10)]


def sig(symbols, p_up=0.6, atr=0.02):
    n = len(symbols)

    def f(v):
        return np.full(n, v, float)

    return {"symbol": np.array(symbols), "p_up": f(p_up), "p_flat": f(0.2), "p_bp": f(0.6),
            "sq": f(0.6), "p_stressed": f(0.1), "p_bear": f(0.1), "gap": f(0.0),
            "vol_20": f(0.01), "atr_pct": f(atr)}


def make_sim(risk=None, params=None, costs=ZERO):
    return PortfolioSim(params or StrategyParams(), costs, risk or RiskConfig(max_drawdown_pct=0.9),
                        SizingConfig(), 1_000_000.0)


def enter(sim, symbol="A", price=100.0):
    sim.step(D[0], {symbol: (price, price, price, price)}, sig([symbol]))
    sim.step(D[1], {symbol: (price, price + 0.5, price - 0.5, price)}, None)
    assert symbol in sim.positions
    return sim.positions[symbol]


def test_entry_fills_next_open_with_expected_size_and_levels():
    sim = make_sim()
    sim.step(D[0], {"A": (100, 100, 100, 100)}, sig(["A"]))
    assert not sim.positions and len(sim.pending_entries) == 1  # nothing fills at the signal close
    sim.step(D[1], {"A": (100, 100.5, 99.5, 100)}, None)
    p = sim.positions["A"]
    assert p.shares == 1000 and p.entry_px == 100
    assert p.stop == pytest.approx(96.0) and p.target == pytest.approx(106.0)


def test_slippage_and_costs_are_charged():
    c = CostConfig()
    sim = make_sim(costs=c)
    sim.step(D[0], {"A": (100, 100, 100, 100)}, sig(["A"]))
    sim.step(D[1], {"A": (100, 100.5, 99.5, 100)}, None)
    p = sim.positions["A"]
    assert p.entry_px == pytest.approx(100 * (1 + c.slippage_bps / 1e4))
    assert p.entry_costs > 0 and sim.cash < 1_000_000 - p.shares * p.entry_px


@pytest.mark.parametrize(
    "bar,expected_exit,reason",
    [
        ((100, 101, 95, 97), 96.0, "stop"),
        ((100, 107, 99, 105), 106.0, "target"),
        ((100, 107, 95, 100), 96.0, "stop"),  # both touched: stop wins
        ((94, 95, 93, 94), 94.0, "stop (gap)"),
    ],
)
def test_exit_rules(bar, expected_exit, reason):
    sim = make_sim()
    enter(sim)
    sim.step(D[2], {"A": bar}, None)
    assert "A" not in sim.positions
    t = sim.trades[0]
    assert t.exit_px == pytest.approx(expected_exit) and t.reason == reason
    assert t.pnl == pytest.approx((expected_exit - 100) * 1000)


def test_time_stop_exits_at_following_open():
    sim = make_sim(params=StrategyParams(max_hold=3))
    enter(sim)  # days_held = 1 after D[1]
    flat = (100, 100.5, 99.5, 100)
    sim.step(D[2], {"A": flat}, None)
    assert "A" in sim.positions
    sim.step(D[3], {"A": flat}, None)  # days_held = 3 -> exit queued
    assert "A" in sim.positions and sim.pending_exits["A"] == "time"
    sim.step(D[4], {"A": (101, 101.5, 100.5, 101)}, None)
    assert "A" not in sim.positions and sim.trades[0].exit_date == D[4].strftime("%Y-%m-%d")
    assert sim.trades[0].exit_px == 101


def test_equity_reconciles_with_cash_and_positions():
    sim = make_sim(costs=CostConfig())
    pos = enter(sim)
    r = sim.step(D[2], {"A": (100, 103, 99, 102)}, None)
    assert pos.shares in (999, 1000)
    assert r.equity == pytest.approx(sim.cash + pos.shares * 102)


def test_drawdown_triggers_persistent_kill_switch_and_blocks_entries():
    sim = make_sim(risk=RiskConfig(max_drawdown_pct=0.03, daily_loss_limit_pct=0.5))
    enter(sim)
    r = sim.step(D[2], {"A": (60, 61, 59, 60), "B": (50, 50, 50, 50)}, sig(["B"]), record_decisions=True)
    assert sim.risk.state.kill_switch
    assert any("KILL SWITCH" in e for e in r.events)
    assert r.decisions[0]["action"] == "blocked: kill switch" and not sim.pending_entries
    r2 = sim.step(D[3], {"B": (50, 50, 50, 50)}, sig(["B"]), record_decisions=True)
    assert not sim.pending_entries and sim.risk.state.kill_switch
    assert r2.decisions[0]["action"] == "blocked: kill switch"


def test_kill_switch_flattens_open_positions_at_next_open():
    sim = make_sim(risk=RiskConfig(max_drawdown_pct=0.003, daily_loss_limit_pct=0.5))
    enter(sim, "A")
    sim.step(D[2], {"A": (97, 97, 96.5, 96.6)}, None)  # 0.34% unrealised loss trips switch
    assert sim.risk.state.kill_switch and sim.pending_exits.get("A") == "kill switch"
    sim.step(D[3], {"A": (96, 96, 96, 96)}, None)
    assert not sim.positions and sim.trades[-1].reason == "kill switch"


def test_daily_loss_limit_halts_only_that_day():
    sim = make_sim(risk=RiskConfig(max_drawdown_pct=0.9, daily_loss_limit_pct=0.02))
    enter(sim)
    # a 22% gap on a 10% position is a 2.2% hit to equity
    r = sim.step(D[2], {"A": (78, 79, 77, 78), "B": (50, 50, 50, 50)}, sig(["B"]), record_decisions=True)
    assert any("daily loss limit" in e for e in r.events)
    assert r.decisions[0]["action"] == "blocked: daily loss limit"
    r3 = sim.step(D[3], {"B": (50, 50, 50, 50)}, sig(["B"]), record_decisions=True)
    assert r3.decisions[0]["action"] == "order"


def test_position_count_and_gross_caps():
    syms = [f"S{i}" for i in range(20)]
    sim = make_sim(risk=RiskConfig(max_positions=8, max_gross_pct=0.8, max_drawdown_pct=0.9))
    bars = {s: (100, 100.5, 99.5, 100) for s in syms}
    sim.step(D[0], bars, sig(syms))
    assert len(sim.pending_entries) == 8
    sim.step(D[1], bars, None)
    assert len(sim.positions) == 8
    assert sim.gross_value() <= 0.8 * sim.equity() + 1e-6
    assert all(p.shares * 100 <= 0.10 * 1_000_000 + 100 for p in sim.positions.values())


def test_gross_cap_binds_before_count_cap():
    syms = [f"S{i}" for i in range(20)]
    sim = make_sim(risk=RiskConfig(max_positions=20, max_gross_pct=0.35, max_drawdown_pct=0.9))
    bars = {s: (100, 100.5, 99.5, 100) for s in syms}
    sim.step(D[0], bars, sig(syms))
    sim.step(D[1], bars, None)
    assert sim.gross_value() <= 0.35 * sim.equity() + 1e-6 and 3 <= len(sim.positions) <= 4


def test_uncalibrated_model_gets_zero_size():
    sim = make_sim()
    r = sim.step(D[0], {"A": (100, 100, 100, 100)}, sig(["A"]), calibration_ok=False,
                 record_decisions=True)
    assert not sim.pending_entries and "calibration" in r.decisions[0]["action"]


def test_manual_approval_hook_holds_large_orders():
    sim = make_sim(risk=RiskConfig(manual_approval_above=50_000, max_drawdown_pct=0.9))
    r = sim.step(D[0], {"A": (100, 100, 100, 100)}, sig(["A"]), approve=lambda o: False)
    assert not sim.pending_entries and len(r.held_orders) == 1


def test_missing_bar_cannot_exit_but_position_is_carried():
    sim = make_sim()
    enter(sim)
    sim.step(D[2], {"OTHER": (10, 10, 10, 10)}, None)  # A halted
    assert "A" in sim.positions


def test_state_round_trip_preserves_behaviour():
    cfg = Config()
    cfg.costs = ZERO
    cfg.risk = RiskConfig(max_drawdown_pct=0.9)
    sim = PortfolioSim(cfg.strategy, cfg.costs, cfg.risk, cfg.sizing, 1_000_000.0)
    enter(sim)
    clone = PortfolioSim.from_dict(sim.to_dict(), cfg, cfg.strategy)
    bar = {"A": (100, 107, 99, 105)}
    a, b = sim.step(D[2], bar, None), clone.step(D[2], bar, None)
    assert a.equity == pytest.approx(b.equity) and sim.trades[0].pnl == pytest.approx(clone.trades[0].pnl)


def test_kelly_and_caps():
    assert kelly_fraction(0.6, 1.0) == pytest.approx(0.2)
    s, r = SizingConfig(), RiskConfig()
    assert position_fraction(0.44, 3, 2, s, r, True) == 0.0  # below cutoff
    assert position_fraction(0.9, 3, 2, s, r, True) == r.max_position_pct  # capped
    assert position_fraction(0.9, 3, 2, s, r, False) == 0.0  # calibration gate
    assert 0 < position_fraction(0.55, 3, 2, s, r, True) < r.max_position_pct


def test_metrics_and_gates():
    idx = pd.bdate_range("2020-01-01", periods=600)
    rng = np.random.default_rng(0)
    eq = pd.Series(1e6 * np.cumprod(1 + rng.normal(0.002, 0.004, 600)), index=idx)
    trades = pd.DataFrame({"pnl": [1.0] * 70 + [-1.0] * 30, "ret": [0.02] * 70 + [-0.01] * 30})
    m = compute_metrics(eq, trades)
    assert m["sharpe"] > 5 and m["tstat"] > 2 and m["hit_rate"] == pytest.approx(0.7)
    g = evaluate_gates(m, GatesConfig(), {0: 0.3, 1: 0.4, 2: 0.3})
    assert g.passed
    bad = evaluate_gates({**m, "hit_rate": 0.4}, GatesConfig(), {1: 1.0})
    assert not bad.passed and {c.name for c in bad.failing()} == {"Hit rate", "Regimes covered"}
