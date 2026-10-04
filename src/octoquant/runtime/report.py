"""Daily report: trades, P&L, win rate, largest loss, model latency and cost, calibration."""

from __future__ import annotations

from pathlib import Path

from octoquant.config import Config
from octoquant.runtime.store import Store


def render_daily_report(store: Store, date: str | None) -> str:
    eq = store.equity_curve()
    trades = store.trades()
    cal = store.get("calibration") or {}
    latency = store.get("latency_ms")
    lines = [f"# Daily report: {date or 'n/a'}", "", "Paper trading only. No real orders.", ""]
    if eq.empty:
        return "\n".join(lines + ["No equity data yet.", ""])
    last = eq.iloc[-1]
    day_pnl = float(last["equity"] - eq.iloc[-2]["equity"]) if len(eq) > 1 else 0.0
    lines += ["| Metric | Value |", "|---|---:|",
              f"| Equity | Rs {last['equity']:,.0f} |",
              f"| Day P&L | Rs {day_pnl:,.0f} |",
              f"| Drawdown | {last['drawdown']:.2%} |",
              f"| Exposure | {last['exposure']:.0%} |"]
    if len(trades):
        wins = (trades["pnl"] > 0).mean()
        worst = trades.loc[trades["pnl"].idxmin()]
        lines += [f"| Closed trades | {len(trades)} |", f"| Win rate | {wins:.0%} |",
                  f"| Largest loss | Rs {worst['pnl']:,.0f} ({worst['symbol']}, {worst['exit_date']}) |"]
    else:
        lines += ["| Closed trades | 0 |"]
    lines += [f"| Model latency per decision | {latency:.2f} ms |" if latency is not None
              else "| Model latency per decision | n/a |",
              "| Model cost per decision | Rs 0 (local model, no per-call fee) |"]
    if cal:
        ece = f"{cal['ece']:.3f}" if cal.get("ece") is not None else "n/a"
        lines.append(f"| Calibration | {'pass' if cal.get('ok') else 'FAIL'} "
                     f"(ECE {ece}, n={cal.get('n')}, {cal.get('source')}) |")
    lines.append("")
    return "\n".join(lines)


def write_daily_report(cfg: Config, store: Store, date: str | None) -> Path:
    out = Path(cfg.runtime.reports_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"daily_{date or 'latest'}.md"
    path.write_text(render_daily_report(store, date))
    return path
