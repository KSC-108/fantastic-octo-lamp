"""Live dashboard: signals, probabilities, confidence, action taken and result."""

from __future__ import annotations

import hmac
import os
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from octoquant.config import Config
from octoquant.research import load_strategy
from octoquant.runtime.runner import PaperRunner
from octoquant.runtime.store import Store

PAGE = Path(__file__).with_name("dashboard.html")


class KillRequest(BaseModel):
    reason: str = "manual"


class TicketRequest(BaseModel):
    strategy: str
    expiry: str | None = None
    lots: int = Field(1, ge=1, le=500)
    width: int | None = Field(None, ge=0, le=60)
    wing: int | None = Field(None, ge=1, le=60)


def _monthly(eq: pd.DataFrame) -> list[dict]:
    if len(eq) < 2:
        return []
    s = eq.set_index(pd.to_datetime(eq["date"]))["equity"]
    m = s.resample("ME").last()
    r = m.pct_change()
    r.iloc[0] = m.iloc[0] / s.iloc[0] - 1
    return [{"year": int(d.year), "month": int(d.month), "ret": float(v)} for d, v in r.items()]


def _clean(df):
    return df.astype(object).where(df.notna(), None).to_dict("records")


def create_app(cfg: Config, store: Store, runner: PaperRunner | None = None,
               options_book=None) -> FastAPI:
    app = FastAPI(title="OctoQuant paper dashboard", docs_url=None, redoc_url=None)

    def require_token(token: str | None) -> None:
        expected = os.environ.get("DASHBOARD_TOKEN", "")
        if not expected or not token or not hmac.compare_digest(token, expected):
            raise HTTPException(403, "invalid or unset DASHBOARD_TOKEN")

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "paper_days": store.paper_days()}

    @app.get("/favicon.ico")
    def favicon():
        return Response(status_code=204)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return PAGE.read_text()

    @app.get("/api/state")
    def state():
        sim = store.get("sim_state") or {}
        eq = store.equity_curve()
        meta = load_strategy(cfg) or {}
        risk = sim.get("risk", {})
        positions = [
            {"symbol": p["symbol"], "shares": p["shares"], "entry_px": p["entry_px"],
             "last": p["last_close"], "pnl": (p["last_close"] - p["entry_px"]) * p["shares"],
             "days": p["days_held"], "stop": p["stop"], "target": p["target"]}
            for p in sim.get("positions", {}).values()
        ]
        last = eq.iloc[-1] if len(eq) else None
        prev = eq.iloc[-2] if len(eq) > 1 else None
        return {
            "mode": "PAPER",
            "as_of": store.get("last_date"),
            "equity": None if last is None else float(last["equity"]),
            "day_change": None if prev is None else float(last["equity"] / prev["equity"] - 1),
            "drawdown": None if last is None else float(last["drawdown"]),
            "exposure": None if last is None else float(last["exposure"]),
            "kill_switch": bool(risk.get("kill_switch", False)),
            "kill_reason": risk.get("kill_reason", ""),
            "strategy": {"accepted": meta.get("accepted"), "data_source": meta.get("data_source"),
                         "created": meta.get("created")},
            "calibration": store.get("calibration"),
            "latency_ms": store.get("latency_ms"),
            "positions": positions,
            "pending_entries": sim.get("pending_entries", []),
            "decisions": _clean(store.latest_decisions().head(40)),
            "trades": _clean(store.trades(15)),
            "events": store.recent_events(15),
        }

    @app.get("/api/equity")
    def equity():
        return _clean(store.equity_curve()[["date", "equity", "drawdown"]])

    @app.get("/api/analytics")
    def analytics():
        eq = store.equity_curve()
        tr = store.trades()
        return {"monthly": _monthly(eq), "trade_returns": [float(x) for x in tr["ret"].dropna()],
                "drawdown": _clean(eq[["date", "drawdown"]]) if len(eq) else []}

    # ---- options ---------------------------------------------------------------------------
    @app.get("/api/options/state")
    def options_state():
        from octoquant.options.strategies import STRATEGIES

        daily = store.frame("SELECT * FROM opt_daily ORDER BY date")
        trades = store.frame("SELECT * FROM opt_trades ORDER BY id DESC LIMIT 25")
        view = options_book.state_view() if options_book is not None else {"positions": [], "pending": []}
        return {**view, "enabled": options_book is not None, "paper_enabled": cfg.options.paper_enabled,
                "lot_size": cfg.options.lot_size, "underlying": cfg.options.underlying,
                "chain_source": cfg.options.source,
                "strategies": [{"name": k, "label": v.label, "view": v.view, "credit": v.credit,
                                "defined_risk": v.defined_risk} for k, v in STRATEGIES.items()],
                "daily": _clean(daily), "trades": _clean(trades)}

    @app.get("/api/options/backtest")
    def options_backtest():
        from octoquant.options.paper import BACKTEST_KEY

        return store.get(BACKTEST_KEY) or {"results": []}

    def need_book():
        if options_book is None:
            raise HTTPException(503, "options book not attached")
        return options_book

    @app.post("/api/options/ticket")
    def options_ticket(body: TicketRequest, x_dashboard_token: str | None = Header(default=None)):
        require_token(x_dashboard_token)
        ok, msg = need_book().ticket(body.strategy, body.expiry, body.lots, body.width, body.wing)
        if not ok:
            raise HTTPException(400, msg)
        return {"ok": True, "message": msg}

    @app.post("/api/options/close/{position_id}")
    def options_close(position_id: int, x_dashboard_token: str | None = Header(default=None)):
        require_token(x_dashboard_token)
        if not need_book().close(position_id):
            raise HTTPException(404, "no such open position")
        return {"ok": True}

    @app.post("/api/kill")
    def kill(body: KillRequest, x_dashboard_token: str | None = Header(default=None)):
        require_token(x_dashboard_token)
        if runner is None:
            raise HTTPException(503, "runner not attached")
        runner.set_kill_switch(True, body.reason[:200])
        return {"kill_switch": True}

    @app.post("/api/resume")
    def resume(x_dashboard_token: str | None = Header(default=None)):
        require_token(x_dashboard_token)
        if runner is None:
            raise HTTPException(503, "runner not attached")
        runner.set_kill_switch(False, "cleared by operator")
        return {"kill_switch": False}

    return app
