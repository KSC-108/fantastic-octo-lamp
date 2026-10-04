"""Final check before any real money: "WHAT COULD BLOW UP THIS ACCOUNT?"

Every item must be clean. This build has no live broker adapter, so the preflight can never
clear live trading here; the report says exactly what stands in the way.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from octoquant.config import Config, RiskConfig, StrategyParams
from octoquant.engine import PortfolioSim
from octoquant.research import load_strategy
from octoquant.review import BOUNDS
from octoquant.risk import RiskManager
from octoquant.runtime.store import Store


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    risk: str


@dataclass
class PreflightReport:
    checks: list[Check]

    @property
    def cleared(self) -> bool:
        return all(c.ok for c in self.checks)


def kill_switch_drill(cfg: Config) -> tuple[bool, str]:
    """Scripted crash: a held position gaps down. The switch must trip, flatten and block entries."""
    import numpy as np

    risk = RiskConfig(**{**cfg.risk.model_dump(), "max_drawdown_pct": 0.03})
    sim = PortfolioSim(StrategyParams(), cfg.costs, risk, cfg.sizing, 1_000_000.0)
    f = lambda v: np.full(1, v, float)  # noqa: E731
    sig = {"symbol": np.array(["X"]), "p_up": f(.6), "p_flat": f(.2), "p_bp": f(.6), "sq": f(.6),
           "p_stressed": f(.1), "p_bear": f(.1), "gap": f(0.), "vol_20": f(.01), "atr_pct": f(.02)}
    t0 = pd.Timestamp("2024-01-01")
    flat = (100.0, 100.5, 99.5, 100.0)
    sim.step(t0, {"X": flat}, sig)
    sim.step(t0 + pd.Timedelta(days=1), {"X": flat}, None)
    sim.step(t0 + pd.Timedelta(days=2), {"X": (60.0, 61.0, 59.0, 60.0), "Y": flat}, sig)
    sim.step(t0 + pd.Timedelta(days=3), {"X": (60.0, 60.0, 60.0, 60.0), "Y": flat}, sig)
    tripped = sim.risk.state.kill_switch
    flat_ok = not sim.positions and not sim.pending_entries
    return tripped and flat_ok, f"tripped={tripped}, flattened and blocked={flat_ok}"


def run_preflight(cfg: Config, store: Store | None = None,
                  attest_trade_only_keys: bool = False) -> PreflightReport:
    meta = load_strategy(cfg) or {}
    checks: list[Check] = []

    def add(name, ok, detail, risk):
        checks.append(Check(name, bool(ok), detail, risk))

    add("Strategy passed the acceptance gates", meta.get("accepted") is True,
        "accepted" if meta.get("accepted") else "no accepted strategy on file",
        "Trading a strategy that never cleared out-of-sample gates is gambling on a backtest.")
    add("Evidence is from real market data", meta.get("data_source") not in (None, "synthetic"),
        f"data source: {meta.get('data_source')}",
        "Synthetic results prove the machinery runs, not that an edge exists.")
    risk_ok = (cfg.risk.max_position_pct <= 0.25 and cfg.risk.max_drawdown_pct <= 0.25
               and cfg.risk.daily_loss_limit_pct <= 0.05)
    risk_fields = set(RiskConfig.model_fields)
    delegated = bool(risk_fields & set(BOUNDS))
    add("Hard limits are in code and not delegated to a model",
        risk_ok and not delegated and isinstance(PortfolioSim(StrategyParams(), cfg.costs, cfg.risk,
                                                              cfg.sizing, 1.0).risk, RiskManager),
        f"limits within sane bounds={risk_ok}; slow brain can edit a risk field={delegated}",
        "A model that can change its own limits will eventually widen them after a drawdown.")
    ok, detail = kill_switch_drill(cfg)
    add("Kill switch fires in simulation", ok, detail,
        "An untested kill switch is a hope, not a control.")
    add("Calibration passes", meta.get("calibration_ok") is True,
        f"calibration ok={meta.get('calibration_ok')}",
        "Kelly sizing on over-confident probabilities over-bets and compounds losses.")
    covered = sum(1 for s in (meta.get("regimes") or {}).values() if s >= cfg.gates.min_regime_share)
    add("Test period covers more than one market regime", covered >= cfg.gates.min_regimes,
        f"{covered} regimes with at least {cfg.gates.min_regime_share:.0%} of test days",
        "A strategy validated in one regime tends to break when the regime changes.")
    days = store.paper_days() if store else 0
    add("Paper track record is long enough", days >= cfg.runtime.min_paper_days,
        f"{days} paper days, need {cfg.runtime.min_paper_days}",
        "Live fills, data delays and holidays only show up in live operation.")
    gi = Path(".gitignore")
    ignored = gi.exists() and ".env" in gi.read_text().split()
    tracked = False
    try:
        out = subprocess.run(["git", "ls-files", ".env"], capture_output=True, text=True, timeout=10)
        tracked = bool(out.stdout.strip())
    except Exception:
        pass
    add("Secrets stay out of the repository", ignored and not tracked,
        f".env ignored={ignored}, tracked={tracked}", "A leaked API key can trade or drain the account.")
    add("Broker keys are trade-only with withdrawals disabled", attest_trade_only_keys,
        "operator attestation " + ("given" if attest_trade_only_keys else "not given"),
        "Withdrawal-capable keys turn any compromise into a loss of principal.")
    add("A live broker adapter exists and has been tested", False,
        "this build ships a paper broker only",
        "There is no tested path for real orders, order rejects, partial fills or reconciliation.")
    return PreflightReport(checks)


def render_preflight(report: PreflightReport) -> str:
    lines = ["# Preflight report", "", "## WHAT COULD BLOW UP THIS ACCOUNT?", ""]
    for c in report.checks:
        lines.append(f"- **{'CLEAN' if c.ok else 'OPEN'}: {c.name}.** {c.risk} ({c.detail})")
    verdict = ("CLEARED for the next stage." if report.cleared
               else "NOT CLEARED. Refusing to go live until every item above is clean.")
    return "\n".join(lines + ["", f"**Verdict: {verdict}**", ""])


def write_preflight(report: PreflightReport, cfg: Config) -> Path:
    path = Path(cfg.runtime.reports_dir) / "preflight.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_preflight(report))
    return path
