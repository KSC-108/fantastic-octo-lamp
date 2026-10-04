"""Strategy research. Parameters are chosen on a validation window only; the test window is
evaluated once, with the chosen parameters, against the acceptance gates.

The number of trials is recorded because the more combinations tried, the more likely one looks
good by luck. A strategy that survives the gates on the one-shot test is still only evidence,
not proof.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from octoquant.calibration import CalibrationReport, assess_calibration
from octoquant.config import Config, StrategyParams
from octoquant.engine import BarIndex, SignalIndex, run_backtest
from octoquant.metrics import GateResult, compute_metrics, evaluate_gates, regime_shares
from octoquant.walkforward import Dataset, walk_forward_signals


@dataclass
class ResearchResult:
    accepted: bool
    params: StrategyParams
    n_trials: int
    val_metrics: dict
    test_metrics: dict
    gates: GateResult
    calibration: CalibrationReport
    regimes: dict[int, float]
    windows: dict[str, str]
    data_source: str
    universe_size: int
    created: str
    trials: pd.DataFrame = field(default_factory=pd.DataFrame)
    signals: pd.DataFrame | None = None


def calibration_gate_series(
    signals: pd.DataFrame, labels: pd.DataFrame, cfg: Config, step: int = 21
) -> pd.Series:
    """For each date: was p_up calibrated on predictions whose outcomes had resolved by then?"""
    data = signals.merge(labels[["date", "symbol", "y_dir"]], on=["date", "symbol"], how="left")
    dates = pd.DatetimeIndex(sorted(data["date"].unique()))
    ok = pd.Series(False, index=dates)
    e, w = cfg.model.embargo, cfg.calibration.window_days
    d = data["date"].to_numpy()
    p = data["p_up"].to_numpy(float)
    y = (data["y_dir"] == 2).to_numpy(float)
    unresolved = data["y_dir"].isna().to_numpy()
    for i in range(0, len(dates), step):
        hi = dates[max(0, i - e)]
        lo = dates[max(0, i - e - w)]
        m = (d <= hi.to_datetime64()) & (d >= lo.to_datetime64()) & ~unresolved
        status = assess_calibration(p[m], y[m], cfg.calibration).ok
        ok.iloc[i : i + step] = status
    return ok


def base_rates(labels: pd.DataFrame, before: pd.Timestamp) -> dict[str, float]:
    """Label prevalence on data strictly before the out-of-sample period."""
    lab = labels[labels["date"] < before]
    return {
        "up": float((lab["y_dir"].dropna() == 2).mean()),
        "bp": float(lab["y_bp"].dropna().mean()),
        "sq": float(lab["y_sq"].dropna().mean()),
    }


def _grid(cfg: Config, base: dict[str, float]) -> list[StrategyParams]:
    r = cfg.research
    combos = list(itertools.product(r.lift_dir, r.lift_bp, r.lift_sq, r.max_stressed, r.max_bear,
                                    r.stop_atr, r.target_atr, r.max_hold))
    rng = np.random.default_rng(r.seed)
    if len(combos) > r.max_trials:
        pick = rng.choice(len(combos), size=r.max_trials, replace=False)
        combos = [combos[i] for i in sorted(pick)]
    return [
        cfg.strategy.model_copy(update=dict(
            tau_dir=round(base["up"] * ld, 4), tau_bp=round(base["bp"] * lb, 4),
            tau_sq=round(base["sq"] * lq, 4), max_stressed=ms, max_bear=mb,
            stop_atr=s, target_atr=t, max_hold=h))
        for ld, lb, lq, ms, mb, s, t, h in combos
    ]


def run_research(
    ds: Dataset,
    cfg: Config,
    signals: pd.DataFrame | None = None,
    progress: Callable[[str], None] | None = None,
) -> ResearchResult:
    say = progress or (lambda _m: None)
    if signals is None:
        signals = walk_forward_signals(ds, cfg, progress)
    cal_ok = calibration_gate_series(signals, ds.labels, cfg)
    dates = pd.DatetimeIndex(sorted(signals["date"].unique()))
    cut = int(len(dates) * cfg.research.val_frac)
    val_lo, val_hi, test_lo, test_hi = dates[0], dates[cut - 1], dates[cut], dates[-1]

    bars, sigs = BarIndex(ds.panel.stocks), SignalIndex(signals)
    candidates = _grid(cfg, base_rates(ds.labels, val_lo))
    rows = []
    for i, p in enumerate(candidates):
        res = run_backtest(bars, sigs, p, cfg, val_lo, val_hi, cal_ok)
        m = compute_metrics(res.equity, res.trades, res.exposure)
        rows.append({**p.model_dump(), **{f"val_{k}": v for k, v in m.items()}})
        if (i + 1) % 20 == 0:
            say(f"validation trial {i + 1}/{len(candidates)}")
    trials = pd.DataFrame(rows)

    eligible = trials[
        (trials["val_n_trades"] >= cfg.gates.min_trades)
        & (trials["val_max_drawdown"] < cfg.gates.max_drawdown)
    ]
    pool = eligible if len(eligible) else trials
    best = pool.sort_values("val_sharpe", ascending=False).iloc[0]
    params = cfg.strategy.model_copy(
        update={k: float(best[k]) for k in ("tau_dir", "tau_bp", "tau_sq", "max_stressed",
                                            "max_bear", "stop_atr", "target_atr")}
        | {"max_hold": int(best["max_hold"])}
    )
    val_metrics = {k[4:]: best[k] for k in trials.columns if k.startswith("val_")}

    test = run_backtest(bars, sigs, params, cfg, test_lo, test_hi, cal_ok)
    test_metrics = compute_metrics(test.equity, test.trades, test.exposure)
    shares = regime_shares(ds.regime, test_lo, test_hi)
    gates = evaluate_gates(test_metrics, cfg.gates, shares)

    lab = signals.merge(ds.labels[["date", "symbol", "y_dir"]], on=["date", "symbol"], how="left")
    lab = lab[(lab["date"] >= test_lo) & (lab["date"] <= test_hi)]
    calib = assess_calibration(
        lab["p_up"].to_numpy(float), (lab["y_dir"] == 2).to_numpy(float), cfg.calibration
    )
    return ResearchResult(
        accepted=bool(gates.passed and calib.ok),
        params=params,
        n_trials=len(candidates),
        val_metrics=val_metrics,
        test_metrics=test_metrics,
        gates=gates,
        calibration=calib,
        regimes=shares,
        windows={"oos_start": str(val_lo.date()), "val_end": str(val_hi.date()),
                 "test_start": str(test_lo.date()), "test_end": str(test_hi.date())},
        data_source=ds.panel.source,
        universe_size=len(ds.panel.symbols),
        created=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        trials=trials,
        signals=signals,
    )


# ---- documents --------------------------------------------------------------------------------

def _entry_text(p: StrategyParams) -> str:
    parts = [f"P(up) >= {p.tau_dir:.2f}", f"P(buying pressure) >= {p.tau_bp:.2f}",
             f"setup quality >= {p.tau_sq:.2f}", f"P(stressed) <= {p.max_stressed:.2f}",
             f"P(bear regime) <= {p.max_bear:.2f}"]
    if p.max_gap is not None:
        parts.append(f"|gap| <= {p.max_gap:.1%}")
    if p.max_vol20 is not None:
        parts.append(f"20-day volatility <= {p.max_vol20:.1%}")
    return "At the close of day t, buy at the next open when ALL hold: " + "; ".join(parts) + "."


def invalidation_rules(cfg: Config, test_hit_rate: float) -> dict:
    return {
        "max_drawdown_pct": cfg.risk.max_drawdown_pct,
        "calibration_max_ece": cfg.calibration.max_ece,
        "hit_rate_floor": round(max(0.0, test_hit_rate - 0.15), 3),
        "hit_rate_window_trades": 50,
    }


def write_strategy_files(res: ResearchResult, cfg: Config, md_path: str | Path | None = None,
                         yaml_path: str | Path | None = None) -> tuple[Path, Path]:
    md_path = Path(md_path or cfg.runtime.strategy_md)
    yaml_path = Path(yaml_path or Path(cfg.runtime.artifacts_dir) / "strategy.yaml")
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    p, tm, vm = res.params, res.test_metrics, res.val_metrics
    inval = invalidation_rules(cfg, tm.get("hit_rate", 0.0))
    status = "ACCEPTED" if res.accepted else "REJECTED"

    yaml_path.write_text(yaml.safe_dump({
        "accepted": res.accepted, "created": res.created, "data_source": res.data_source,
        "universe_size": res.universe_size, "windows": res.windows, "n_trials": res.n_trials,
        "params": p.model_dump(), "invalidation": inval,
        "test_metrics": {k: (float(v) if v == v else None) for k, v in tm.items()},
        "gates_passed": res.gates.passed, "calibration_ok": res.calibration.ok,
        "regimes": {str(k): v for k, v in res.regimes.items()},
    }, sort_keys=False))

    lines = [f"# Strategy: {status}", "",
             f"Generated {res.created} by `octoquant research`. Data source: **{res.data_source}**."]
    if res.data_source == "synthetic":
        lines += ["", "> **Synthetic data.** This result shows the machinery runs. It is not evidence of a "
                  "tradable edge on NSE."]
    lines += ["", "## Rules", "",
              f"- **Entry.** {_entry_text(p)}",
              f"- **Timeframe.** Daily bars. Maximum hold {p.max_hold} sessions, then exit at the next open.",
              f"- **Stop.** Entry price x (1 - {p.stop_atr:g} x ATR14%). Gap-aware: a gap through the stop "
              "fills at the open.",
              f"- **Take profit.** Entry price x (1 + {p.target_atr:g} x ATR14%).",
              f"- **Sizing.** Capped fractional Kelly: {cfg.sizing.kelly_fraction:g} of full Kelly, at most "
              f"{cfg.risk.max_position_pct:.0%} of equity per name, zero if calibration fails.",
              f"- **Invalidation.** Stop trading and require human review if any of: drawdown reaches "
              f"{inval['max_drawdown_pct']:.0%}; rolling ECE exceeds {inval['calibration_max_ece']:.2f}; "
              f"hit rate over the last {inval['hit_rate_window_trades']} trades falls below "
              f"{inval['hit_rate_floor']:.0%}.",
              "", "## Acceptance gates (held-out test window)", "",
              "| Gate | Value | Rule | Result |", "|---|---:|---|---|"]
    for c in res.gates.checks:
        v = f"{c.value:.2%}" if c.name in ("Max drawdown", "Hit rate") else f"{c.value:.2f}"
        t = f"{c.threshold:.0%}" if c.name in ("Max drawdown", "Hit rate") else f"{c.threshold:g}"
        lines.append(f"| {c.name} | {v} | {c.rule} {t} | {'pass' if c.ok else 'FAIL'} |")
    lines += ["", f"Calibration on the test window: {'pass' if res.calibration.ok else 'FAIL'} "
              f"(ECE {res.calibration.ece:.3f}, Brier {res.calibration.brier:.3f}, n={res.calibration.n}; "
              f"{res.calibration.reason}).",
              "", "## Windows and search", "",
              f"- Out-of-sample signals from {res.windows['oos_start']}. Validation to {res.windows['val_end']}, "
              f"test {res.windows['test_start']} to {res.windows['test_end']}.",
              f"- Parameters chosen on validation only from {res.n_trials} trials (validation Sharpe "
              f"{vm.get('sharpe', 0):.2f}). The test window was evaluated once.",
              "- Test regime shares (0 bear, 1 chop, 2 bull): "
              + ", ".join(f"{k}: {v:.0%}" for k, v in sorted(res.regimes.items())) + ".",
              f"- Test CAGR {tm.get('cagr', 0):.1%}, annualised volatility {tm.get('ann_vol', 0):.1%}, "
              f"{tm.get('n_trades', 0)} trades, average exposure {tm.get('exposure', 0):.0%}.",
              "", "## Caveats", "",
              "- More trials raise the chance that a result is luck. Treat acceptance as evidence, not proof.",
              "- Cost rates and slippage are assumptions. Verify them against your contract notes.",
              "- If the universe is today's index constituents, survivorship bias flatters history.",
              "- Paper trading only. Past or simulated performance does not predict future results.", ""]
    md_path.write_text("\n".join(lines))
    return md_path, yaml_path


def load_strategy(cfg: Config, path: str | Path | None = None) -> dict | None:
    path = Path(path or Path(cfg.runtime.artifacts_dir) / "strategy.yaml")
    if not path.exists():
        return None
    return yaml.safe_load(path.read_text())
