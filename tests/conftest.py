import pytest

from octoquant.data.synthetic import generate_synthetic


@pytest.fixture(scope="session")
def small_panel():
    return generate_synthetic(symbols=[f"S{i:02d}" for i in range(8)], years=4, seed=3, edge=0.002)


@pytest.fixture(scope="session")
def null_panel():
    return generate_synthetic(symbols=[f"S{i:02d}" for i in range(8)], years=4, seed=5, edge=0.0)


import copy  # noqa: E402

import joblib  # noqa: E402

from helpers import SYMS, make_small_cfg  # noqa: E402
from octoquant.research import run_research, write_strategy_files  # noqa: E402
from octoquant.walkforward import build_dataset, fit_final_bank  # noqa: E402


@pytest.fixture(scope="session")
def trained(tmp_path_factory):
    """Research once on a small synthetic market that stops 40 days short of its end."""
    root = tmp_path_factory.mktemp("trained")
    cfg = make_small_cfg(root)
    full = generate_synthetic(symbols=SYMS, years=6.5, seed=12, edge=0.003)
    dates = full.dates
    ds = build_dataset(full.truncate(dates[-41]), cfg)
    res = run_research(ds, cfg)
    write_strategy_files(res, cfg)
    bank, _ = fit_final_bank(ds, cfg)
    joblib.dump(bank, root / "artifacts" / "bank.joblib")
    res.signals.to_pickle(root / "artifacts" / "oos_signals.pkl.gz", compression="gzip")
    return {"cfg": cfg, "full": full, "dates": dates, "res": res, "ds": ds, "root": root}


@pytest.fixture
def rt_cfg(trained, tmp_path):
    """Config sharing the trained artifacts but with its own database."""
    cfg = copy.deepcopy(trained["cfg"])
    cfg.runtime.db_path = str(tmp_path / "run.db")
    return cfg
