"""Performance metrics and the acceptance gates."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from octoquant.config import GatesConfig

TRADING_DAYS = 252


def compute_metrics(equity: pd.Series, trades: pd.DataFrame, exposure: pd.Series | None = None) -> dict:
    """Risk-free rate is taken as zero and idle cash earns nothing, which is conservative."""
    rets = equity.pct_change().dropna()
    n = len(rets)
    if n < 2:
        return {"days": n, "sharpe": 0.0, "tstat": 0.0, "max_drawdown": 0.0, "hit_rate": 0.0,
                "n_trades": 0, "years": 0.0, "total_return": 0.0, "cagr": 0.0}
    sd = rets.std(ddof=1)
    sharpe = float(rets.mean() / sd * np.sqrt(TRADING_DAYS)) if sd > 0 else 0.0
    tstat = float(rets.mean() / (sd / np.sqrt(n))) if sd > 0 else 0.0
    dd = float((1 - equity / equity.cummax()).max())
    years = n / TRADING_DAYS
    total = float(equity.iloc[-1] / equity.iloc[0] - 1)
    cagr = float((equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1) if years > 0 else 0.0
    out = {
        "days": n, "years": years, "total_return": total, "cagr": cagr, "sharpe": sharpe,
        "tstat": tstat, "max_drawdown": dd, "n_trades": int(len(trades)),
        "ann_vol": float(sd * np.sqrt(TRADING_DAYS)),
        "exposure": float(exposure.mean()) if exposure is not None and len(exposure) else 0.0,
    }
    if len(trades):
        wins, losses = trades[trades["pnl"] > 0], trades[trades["pnl"] <= 0]
        out["hit_rate"] = float((trades["pnl"] > 0).mean())
        out["avg_ret"] = float(trades["ret"].mean())
        gl = -losses["pnl"].sum()
        out["profit_factor"] = float(wins["pnl"].sum() / gl) if gl > 0 else float("inf")
        out["payoff"] = (
            float(wins["ret"].mean() / -losses["ret"].mean())
            if len(wins) and len(losses) and losses["ret"].mean() < 0 else float("nan")
        )
    else:
        out.update({"hit_rate": 0.0, "avg_ret": 0.0, "profit_factor": 0.0, "payoff": float("nan")})
    return out


@dataclass
class GateCheck:
    name: str
    value: float
    threshold: float
    ok: bool
    rule: str

    def as_dict(self) -> dict:
        return {"name": self.name, "value": self.value, "threshold": self.threshold,
                "ok": self.ok, "rule": self.rule}


@dataclass
class GateResult:
    passed: bool
    checks: list[GateCheck]

    def failing(self) -> list[GateCheck]:
        return [c for c in self.checks if not c.ok]


def regime_shares(regime: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> dict[int, float]:
    r = regime[(regime.index >= start) & (regime.index <= end)].dropna()
    if r.empty:
        return {}
    return {int(k): float(v) for k, v in r.value_counts(normalize=True).items()}


def evaluate_gates(m: dict, g: GatesConfig, shares: dict[int, float]) -> GateResult:
    covered = sum(1 for s in shares.values() if s >= g.min_regime_share)
    checks = [
        GateCheck("Sharpe ratio", m["sharpe"], g.min_sharpe, m["sharpe"] > g.min_sharpe, ">"),
        GateCheck("Max drawdown", m["max_drawdown"], g.max_drawdown,
                  m["max_drawdown"] < g.max_drawdown, "<"),
        GateCheck("Hit rate", m["hit_rate"], g.min_hit_rate, m["hit_rate"] > g.min_hit_rate, ">"),
        GateCheck("t-statistic", m["tstat"], g.min_tstat, m["tstat"] > g.min_tstat, ">"),
        GateCheck("Test span (years)", m["years"], g.min_test_years,
                  m["years"] >= g.min_test_years, ">="),
        GateCheck("Regimes covered", float(covered), float(g.min_regimes),
                  covered >= g.min_regimes, ">="),
        GateCheck("Trades", float(m["n_trades"]), float(g.min_trades),
                  m["n_trades"] >= g.min_trades, ">="),
    ]
    return GateResult(all(c.ok for c in checks), checks)
