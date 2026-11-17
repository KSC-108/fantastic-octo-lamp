import math

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from octoquant.config import Config
from octoquant.data.synthetic import generate_synthetic
from octoquant.options.chain import BhavcopyChain, ModelChain, load_bhavcopy, year_frac
from octoquant.options.engine import OptionsSimulator, option_fees, option_fill_price, run_options_backtest
from octoquant.options.paper import BACKTEST_KEY, OptionsPaperBook
from octoquant.options.pricing import bs_greeks, bs_price, implied_vol
from octoquant.options.report import backtest_payload
from octoquant.options.strategies import STRATEGIES, payoff_extremes
from octoquant.runtime.dashboard import create_app
from octoquant.runtime.notify import Notifier
from octoquant.runtime.store import Store


@pytest.fixture(scope="module")
def under():
    return generate_synthetic(symbols=[f"S{i}" for i in range(6)], years=2.5, seed=4).index


@pytest.fixture
def cfg(tmp_path):
    c = Config()
    c.runtime.db_path = str(tmp_path / "o.db")
    c.runtime.reports_dir = str(tmp_path / "reports")
    return c


# ---- pricing ------------------------------------------------------------------------------------
def test_put_call_parity_and_iv_round_trip():
    s, k, t, v, r, q = 22000.0, 22200.0, 10 / 365, 0.14, 0.065, 0.012
    c, p = bs_price(s, k, t, v, "CE", r, q), bs_price(s, k, t, v, "PE", r, q)
    assert c - p == pytest.approx(s * math.exp(-q * t) - k * math.exp(-r * t), abs=1e-6)
    assert implied_vol(c, s, k, t, "CE", r, q) == pytest.approx(v, abs=1e-4)
    assert implied_vol(5000.0, s, 30000, t, "CE", r, q) is None  # above the no-arbitrage bound
    assert bs_price(s, k, 0.0, v, "PE") == pytest.approx(200.0)


@pytest.mark.parametrize("kind", ["CE", "PE"])
def test_greeks_match_finite_differences(kind):
    s, k, t, v = 20000.0, 20100.0, 20 / 365, 0.16
    g = bs_greeks(s, k, t, v, kind)
    h = 1.0
    assert g["delta"] == pytest.approx((bs_price(s + h, k, t, v, kind) - bs_price(s - h, k, t, v, kind)) / 2, rel=1e-3)
    gam = (bs_price(s + h, k, t, v, kind) - 2 * bs_price(s, k, t, v, kind) + bs_price(s - h, k, t, v, kind))
    assert g["gamma"] == pytest.approx(gam, rel=1e-2)
    assert g["vega"] == pytest.approx((bs_price(s, k, t, v + 0.005, kind) - bs_price(s, k, t, v - 0.005, kind)) / 1.0, rel=1e-3)
    assert g["theta"] == pytest.approx(bs_price(s, k, t - 1 / 365, v, kind) - bs_price(s, k, t, v, kind), rel=0.05)


# ---- strategies ---------------------------------------------------------------------------------
def test_iron_condor_extremes_and_undefined_risk():
    legs = [{"kind": "PE", "side": 1, "strike": 900, "premium": 2}, {"kind": "PE", "side": -1, "strike": 950, "premium": 6},
            {"kind": "CE", "side": -1, "strike": 1050, "premium": 6}, {"kind": "CE", "side": 1, "strike": 1100, "premium": 2}]
    mp, ml, bes = payoff_extremes(legs, 1000)
    assert mp == pytest.approx(8) and ml == pytest.approx(42)
    assert [round(b) for b in bes] == [942, 1058]
    strangle = [x for x in legs if x["side"] < 0]
    assert payoff_extremes(strangle, 1000)[1] == float("inf")
    assert payoff_extremes([{"kind": "CE", "side": 1, "strike": 1000, "premium": 5}], 1000)[0] == float("inf")
    assert STRATEGIES["iron_condor"].credit and not STRATEGIES["long_straddle"].credit
    assert STRATEGIES["bull_call_spread"].offsets(4, 3) == [("CE", 1, 0), ("CE", -1, 3)]


def test_costs_charge_stt_on_the_sell_side_only(cfg):
    c = cfg.options.costs
    buy, sell = option_fees(100, 1, 75, c), option_fees(100, -1, 75, c)
    assert sell - buy == pytest.approx(c.stt_sell_premium_pct * 7500 - c.stamp_buy_pct * 7500)
    assert option_fill_price(100, 1, c) > 100 > option_fill_price(100, -1, c)
    assert option_fill_price(0.05, -1, c) == 0.05


# ---- chains -------------------------------------------------------------------------------------
def _write_old_bhavcopy(tmp_path, chain: ModelChain, days, n_strikes=12):
    rows = []
    for d in days:
        for e in chain.expiries(d)[:2]:
            atm = chain.nearest_strike(d, e, chain.spot(d))
            for k in atm + chain.cfg.strike_step * np.arange(-n_strikes, n_strikes + 1):
                for kind in ("CE", "PE"):
                    rows.append({"INSTRUMENT": "OPTIDX", "SYMBOL": "NIFTY", "EXPIRY_DT": e.strftime("%d-%b-%Y"),
                                 "STRIKE_PR": k, "OPTION_TYP": kind,
                                 "OPEN": chain.price(d, e, k, kind, at_open=True), "HIGH": 0, "LOW": 0,
                                 "CLOSE": chain.price(d, e, k, kind), "SETTLE_PR": chain.price(d, e, k, kind),
                                 "CONTRACTS": 10, "VAL_INLAKH": 1, "OPEN_INT": 100, "CHG_IN_OI": 0,
                                 "TIMESTAMP": d.strftime("%d-%b-%Y")})
        rows.append({"INSTRUMENT": "FUTIDX", "SYMBOL": "NIFTY", "EXPIRY_DT": "30-Dec-2030", "STRIKE_PR": 0,
                     "OPTION_TYP": "XX", "OPEN": 1, "HIGH": 1, "LOW": 1, "CLOSE": 1, "SETTLE_PR": 1, "CONTRACTS": 1,
                     "VAL_INLAKH": 1, "OPEN_INT": 1, "CHG_IN_OI": 0, "TIMESTAMP": d.strftime("%d-%b-%Y")})
    path = tmp_path / "fo_bhav.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def test_old_bhavcopy_parses_and_parity_recovers_spot(tmp_path, under, cfg):
    model = ModelChain(under, cfg.options)
    days = model.dates[100:106]
    df = load_bhavcopy([_write_old_bhavcopy(tmp_path, model, days)])
    assert set(df["kind"]) == {"CE", "PE"} and df["date"].nunique() == 6
    bc = BhavcopyChain(df, cfg.options)
    assert bc.spot_source.startswith("put-call parity")
    for d in days:
        assert bc.spot(d) == pytest.approx(model.spot(d), rel=0.01)
        e = bc.expiries(d)[0]
        k = bc.nearest_strike(d, e, bc.spot(d))
        assert bc.price(d, e, k, "CE") == pytest.approx(model.price(d, e, k, "CE"))
        if (e - d).days >= 2:
            assert bc.iv(d, e, k, "CE") == pytest.approx(model.iv(d, e, k, "CE"), abs=0.03)


def test_udiff_bhavcopy_uses_underlying_column(tmp_path, cfg):
    path = tmp_path / "BhavCopy_NSE_FO_0_0_0_20261116_F_0000.csv"
    pd.DataFrame([
        {"TradDt": "2026-11-16", "FinInstrmTp": "IDO", "TckrSymb": "NIFTY", "XpryDt": "2026-11-24",
         "StrkPric": 26000, "OptnTp": kind, "OpnPric": 100, "ClsPric": px, "SttlmPric": px,
         "UndrlygPric": 26010.5, "OpnIntrst": 5, "TtlTradgVol": 9}
        for kind, px in (("CE", 120.0), ("PE", 0.0))
    ] + [{"TradDt": "2026-11-16", "FinInstrmTp": "IDF", "TckrSymb": "NIFTY", "XpryDt": "2026-11-24",
          "StrkPric": 1, "OptnTp": "CE", "OpnPric": 1, "ClsPric": 1, "SttlmPric": 1, "UndrlygPric": 1}]).to_csv(path, index=False)
    df = load_bhavcopy([path])
    assert len(df) == 2 and df["underlying"].iloc[0] == 26010.5
    bc = BhavcopyChain(df, cfg.options)
    d, e = pd.Timestamp("2026-11-16"), pd.Timestamp("2026-11-24")
    assert bc.spot(d) == 26010.5 and bc.price(d, e, 26000, "CE") == 120.0
    assert bc.price(d, e, 26000, "PE") is None  # zero close and settle: no tradable price
    assert year_frac(d, e) == pytest.approx(8 / 365)


def test_model_chain_expiries_follow_weekday_and_roll_for_holidays(under, cfg):
    model = ModelChain(under, cfg.options)
    tuesdays = [e for e in model._expiries if e <= model.dates.max()]
    assert all(e.weekday() <= 1 for e in tuesdays) and all(e in set(model.dates) for e in tuesdays)
    holiday = next(e for e in tuesdays[5:])
    rolled = ModelChain(under[under["date"] != holiday], cfg.options)
    assert holiday - pd.Timedelta(days=1) in rolled._expiries


# ---- simulator ----------------------------------------------------------------------------------
def test_backtest_has_no_look_ahead(under, cfg):
    model = ModelChain(under, cfg.options)
    cut = model.dates[300]
    full = run_options_backtest(model, cfg, end=cut)
    short = run_options_backtest(ModelChain(under[pd.to_datetime(under["date"]) <= cut], cfg.options), cfg)
    pd.testing.assert_series_equal(full.daily["equity"], short.daily["equity"])
    assert len(full.trades) > 20


def test_fills_happen_at_the_next_open(under, cfg):
    model = ModelChain(under, cfg.options)
    res = run_options_backtest(model, cfg)
    t = res.trades
    assert (pd.to_datetime(t["entry_date"]) <= pd.to_datetime(t["exit_date"])).all()
    sim = OptionsSimulator(cfg)
    d0 = model.dates[60]
    e = [x for x in model.expiries(d0) if (x - d0).days >= 3][0]
    ok, _ = sim.queue_entry(model, d0, e, "iron_condor", lots=1)
    assert ok and not sim.state.positions
    rep = sim.step(model.dates[61], model, decide=False)
    pos = next(iter(sim.state.positions.values()))
    leg = pos.legs[0]
    open_px = model.price(model.dates[61], e, leg.strike, leg.kind, at_open=True)
    assert leg.entry_px == pytest.approx(option_fill_price(open_px, leg.side, cfg.options.costs))
    assert len(rep.fills) == 4


def test_sizing_respects_risk_budget_and_margin_cap(under, cfg):
    model = ModelChain(under, cfg.options)
    sim = OptionsSimulator(cfg)
    d = model.dates[80]
    e = [x for x in model.expiries(d) if (x - d).days >= 3][0]
    for name in ("iron_condor", "short_strangle", "long_straddle"):
        legs = sim.build_legs(model, d, e, name, 4, 4)
        sz = sim.size(legs, model.spot(d), sim.equity(), name)
        assert sz["lots"] * sz["risk_lot"] <= cfg.options.risk.risk_per_trade_pct * sim.equity() + 1e-6
        assert sz["lots"] * sz["margin_lot"] <= cfg.options.risk.max_margin_pct * sim.equity() + 1e-6
    ok, msg = sim.queue_entry(model, d, e, "iron_condor", lots=10_000)
    assert not ok and "risk limits allow" in msg


def test_drawdown_kill_switch_flattens_and_halts(under, cfg):
    cfg.options.risk.max_drawdown_pct = 0.002
    cfg.options.strategy.name = "short_straddle"
    res = run_options_backtest(ModelChain(under, cfg.options), cfg)
    assert (res.trades["reason"] == "kill switch").any()
    assert any("kill switch" in msg for _, _, msg in res.events)
    last_exit = pd.to_datetime(res.trades["exit_date"]).max()
    assert (res.daily.set_index(pd.to_datetime(res.daily["date"])).loc[last_exit:, "positions"].iloc[1:] == 0).all()


def test_state_round_trips_through_json(under, cfg):
    import json

    from octoquant.options.engine import SimState

    model = ModelChain(under, cfg.options)
    sim = OptionsSimulator(cfg)
    for d in model.dates[:120]:
        sim.step(d, model)
    again = SimState.from_dict(json.loads(json.dumps(sim.state.to_dict())))
    assert again.to_dict() == sim.state.to_dict()


# ---- paper book and dashboard -------------------------------------------------------------------
def test_paper_book_matches_backtest_and_gates_unvalidated(under, cfg):
    model = ModelChain(under, cfg.options)
    store = Store(cfg.runtime.db_path)
    book = OptionsPaperBook(cfg, store, Notifier("", ""), lambda: model)
    assert book.run().status == "refused"
    days = model.dates[:90]
    for d in days:
        book.load_chain = lambda d=d: model.truncate(d)
        assert book.run(allow_unvalidated=True).status == "ok"
    assert book.run(allow_unvalidated=True).status == "up_to_date"
    bt = run_options_backtest(model, cfg, start=days[0], end=days[-1])
    paper = store.frame("SELECT equity FROM opt_daily ORDER BY date")["equity"]
    np.testing.assert_allclose(paper.values, bt.daily["equity"].values, rtol=1e-12)
    assert len(store.frame("SELECT * FROM opt_trades")) == len(bt.trades)


def test_ticket_checks_date_and_dashboard_endpoints(under, cfg, monkeypatch):
    cfg.options.risk.risk_per_trade_pct = 0.05
    model = ModelChain(under, cfg.options)
    store = Store(cfg.runtime.db_path)
    book = OptionsPaperBook(cfg, store, Notifier("", ""), lambda: model.truncate(model.dates[200]))
    book.run(allow_unvalidated=True)
    ok, msg = book.ticket("short_strangle", None, 1)
    assert ok, msg
    book.load_chain = lambda: model.truncate(model.dates[205])
    ok, msg = book.ticket("iron_condor", None, 1)
    assert not ok and "paper-run" in msg
    assert not book.ticket("nonsense", None, 1)[0]
    book.load_chain = lambda: model.truncate(model.dates[201])
    book.run(allow_unvalidated=True)
    res = run_options_backtest(model, cfg, end=model.dates[200])
    store.set(BACKTEST_KEY, backtest_payload([res], res.strategy))

    monkeypatch.setenv("DASHBOARD_TOKEN", "t0k")
    client = TestClient(create_app(cfg, store, None, book))
    s = client.get("/api/options/state").json()
    assert s["enabled"] and len(s["positions"]) == 1 and s["positions"][0]["payoff"]["breakevens"]
    assert s["positions"][0]["max_loss"] is None  # strangle: undefined risk
    bt = client.get("/api/options/backtest").json()
    assert bt["results"][0]["curve"] and "monthly" in bt["results"][0]
    assert client.post("/api/options/ticket", json={"strategy": "iron_condor"}).status_code == 403
    r = client.post("/api/options/ticket", json={"strategy": "iron_condor"}, headers={"X-Dashboard-Token": "t0k"})
    assert r.status_code == 200, r.text
    pid = s["positions"][0]["id"]
    assert client.post(f"/api/options/close/{pid}", headers={"X-Dashboard-Token": "t0k"}).status_code == 200
    assert client.post("/api/options/close/999", headers={"X-Dashboard-Token": "t0k"}).status_code == 404
    a = client.get("/api/analytics").json()
    assert set(a) == {"monthly", "trade_returns", "drawdown"}
    assert "Options book" in client.get("/").text
