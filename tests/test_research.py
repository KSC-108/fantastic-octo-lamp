import numpy as np
import pandas as pd
import pytest
import yaml

from helpers import SYMS, make_small_cfg
from octoquant.data.synthetic import generate_synthetic
from octoquant.models import ProbabilityBank
from octoquant.research import (
    base_rates,
    calibration_gate_series,
    load_strategy,
    run_research,
    write_strategy_files,
)
from octoquant.walkforward import build_dataset, walk_forward_signals


def test_null_market_is_rejected(tmp_path):
    cfg = make_small_cfg(tmp_path)
    ds = build_dataset(generate_synthetic(symbols=SYMS, years=6.5, seed=5, edge=0.0), cfg)
    res = run_research(ds, cfg)
    assert not res.accepted
    assert res.test_metrics["sharpe"] < cfg.gates.min_sharpe


def test_research_result_is_well_formed(trained):
    res, cfg = trained["res"], trained["cfg"]
    w = res.windows
    assert w["oos_start"] < w["val_end"] < w["test_start"] <= w["test_end"]
    assert res.n_trials == len(res.trials) == 40
    assert res.test_metrics["n_trades"] >= 0 and np.isfinite(res.test_metrics["sharpe"])
    assert res.params.stop_atr in cfg.research.stop_atr
    assert res.params.target_atr in cfg.research.target_atr
    assert res.signals is not None and res.signals["date"].min() == pd.Timestamp(w["oos_start"])


def test_selection_uses_validation_only(trained):
    """The chosen parameters must be the best eligible validation trial, not a test-window pick."""
    res, cfg = trained["res"], trained["cfg"]
    t = res.trials
    elig = t[(t["val_n_trades"] >= cfg.gates.min_trades) & (t["val_max_drawdown"] < cfg.gates.max_drawdown)]
    pool = elig if len(elig) else t
    assert res.val_metrics["sharpe"] == pytest.approx(pool["val_sharpe"].max())


def test_strategy_files_round_trip(trained):
    cfg = trained["cfg"]
    meta = load_strategy(cfg)
    md = open(cfg.runtime.strategy_md).read()
    assert meta["accepted"] == trained["res"].accepted
    assert ("ACCEPTED" in md.splitlines()[0]) == meta["accepted"]
    for section in ("Entry", "Stop", "Take profit", "Invalidation", "Timeframe"):
        assert section in md
    assert meta["data_source"] == "synthetic" and "Synthetic data" in md
    assert set(meta["invalidation"]) >= {"max_drawdown_pct", "calibration_max_ece", "hit_rate_floor"}


def test_walk_forward_never_trains_on_unresolved_labels(trained, monkeypatch):
    ds, cfg = trained["ds"], trained["cfg"]
    seen = []
    orig = ProbabilityBank.fit

    def spy(self, feats, labels, mkt, regime, last_train_date):
        seen.append(last_train_date)
        return orig(self, feats, labels, mkt, regime, last_train_date)

    monkeypatch.setattr(ProbabilityBank, "fit", spy)
    walk_forward_signals(ds, cfg)
    dates = ds.dates
    first = cfg.model.min_train_days + cfg.model.embargo
    for k, cutoff in enumerate(seen):
        block_start = dates[first + k * cfg.model.retrain_every]
        gap = dates.get_loc(block_start) - dates.get_loc(cutoff)
        assert gap >= cfg.model.embargo, "training window reaches into the label horizon"


def test_calibration_gate_is_closed_before_any_history(trained):
    ds, cfg, res = trained["ds"], trained["cfg"], trained["res"]
    cal = calibration_gate_series(res.signals, ds.labels, cfg)
    assert not cal.iloc[:10].any()
    assert cal.iloc[len(cal) // 2 :].any()


def test_base_rates_use_only_pre_oos_data(trained):
    ds, res = trained["ds"], trained["res"]
    cut = pd.Timestamp(res.windows["oos_start"])
    a = base_rates(ds.labels, cut)
    altered = ds.labels.copy()
    altered.loc[altered["date"] >= cut, ["y_dir", "y_bp", "y_sq"]] = 1.0
    assert base_rates(altered, cut) == a


def test_write_strategy_files_handles_rejection(trained, tmp_path):
    cfg = make_small_cfg(tmp_path)
    res = trained["res"]
    res.accepted = False
    md, yml = write_strategy_files(res, cfg)
    assert md.read_text().startswith("# Strategy: REJECTED")
    assert yaml.safe_load(yml.read_text())["accepted"] is False


@pytest.mark.slow
def test_full_size_harness_power_and_size():
    """Null market must be rejected; a strong planted edge should usually be found."""
    from octoquant.config import Config

    out = {}
    for name, edge, seed in (("null", 0.0, 11), ("edge", 0.003, 12)):
        cfg = Config()
        ds = build_dataset(generate_synthetic(years=9, seed=seed, edge=edge), cfg)
        out[name] = run_research(ds, cfg)
    assert not out["null"].accepted
    assert out["edge"].test_metrics["sharpe"] > 1.5
