"""Backtest payloads for the dashboard and a markdown report for humans."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from octoquant.options.engine import OptionsBacktestResult


def _downsample(df: pd.DataFrame, n: int = 500) -> pd.DataFrame:
    if len(df) <= n:
        return df
    idx = np.unique(np.linspace(0, len(df) - 1, n).round().astype(int))
    return df.iloc[idx]


def monthly_returns(daily: pd.DataFrame) -> list[dict]:
    if daily.empty:
        return []
    eq = daily.set_index(pd.to_datetime(daily["date"]))["equity"]
    m = eq.resample("ME").last()
    first = eq.iloc[0]
    r = m.pct_change()
    r.iloc[0] = m.iloc[0] / first - 1
    return [{"year": int(d.year), "month": int(d.month), "ret": float(v)} for d, v in r.items()]


def backtest_payload(results: list[OptionsBacktestResult], primary: str) -> dict:
    out = {"created": datetime.now(UTC).isoformat(timespec="seconds"), "primary": primary, "results": []}
    for r in results:
        d = _downsample(r.daily[["date", "equity", "drawdown", "spot", "atm_iv"]])
        item = r.summary()
        item["curve"] = d.astype(object).where(d.notna(), None).to_dict("records")
        item["trade_pnl"] = [round(float(x), 2) for x in r.trades["pnl"]]
        item["exit_reasons"] = r.trades["reason"].value_counts().to_dict() if len(r.trades) else {}
        if r.strategy == primary:
            item["monthly"] = monthly_returns(r.daily)
            t = r.trades.tail(40).iloc[::-1]
            item["recent_trades"] = t.astype(object).where(t.notna(), None).to_dict("records")
            item["params"] = r.params
        out["results"].append(item)
    return out


def write_backtest_report(results: list[OptionsBacktestResult], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    first = results[0]
    lines = [
        "# Options backtest", "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC. Chain: **{first.chain}** "
        f"({first.vol_source}). Period {first.daily['date'].iloc[0]} to {first.daily['date'].iloc[-1]}.", "",
        "Paper research only, not financial advice. Charges and lot size are assumptions in "
        "`options.costs` and `options.lot_size`; verify them against your broker.", "",
        "| Strategy | Gates | Return | Sharpe | Max DD | Hit rate | Trades | Worst trade (Rs) | Costs (Rs) |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        s = r.summary()
        lines.append(
            f"| {s['label']} | {'pass' if s['accepted'] else 'fail'} | {s['total_return']:+.1%} | "
            f"{s['sharpe']:.2f} | {s['max_drawdown']:.1%} | {s['hit_rate']:.0%} | {s['n_trades']:.0f} | "
            f"{(s['worst_trade'] or 0):,.0f} | {s['costs']:,.0f} |")
    lines += ["", "## Gate detail", ""]
    for r in results:
        failing = ", ".join(c.name for c in r.gates.failing()) or "none"
        lines.append(f"- **{r.summary()['label']}**: failing gates: {failing}")
    if first.chain == "model":
        lines += ["", "## Caveat on the model chain", "",
                  "Prices come from Black-Scholes on the underlying, not from traded premia. Without "
                  "skew and with volatility set from realised vol, results say little about real "
                  "premium-selling P&L. Import NSE bhavcopy files (`options.source: bhavcopy`) for "
                  "evidence that means something."]
    path.write_text("\n".join(lines) + "\n")
    return path
