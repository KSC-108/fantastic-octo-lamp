"""Live dashboard: signals, probabilities, confidence, action taken and result."""

from __future__ import annotations

import hmac
import os
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from octoquant.config import Config
from octoquant.research import load_strategy
from octoquant.runtime.runner import PaperRunner
from octoquant.runtime.store import Store

PAGE = Path(__file__).with_name("dashboard.html")


class KillRequest(BaseModel):
    reason: str = "manual"


def _clean(df):
    return df.astype(object).where(df.notna(), None).to_dict("records")


def create_app(cfg: Config, store: Store, runner: PaperRunner | None = None) -> FastAPI:
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
