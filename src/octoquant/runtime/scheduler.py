"""Daily scheduling in IST. The job runs once per trading day after the configured time."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from octoquant.config import Config
from octoquant.data.base import expected_last_trading_day

IST = ZoneInfo("Asia/Kolkata")
log = logging.getLogger(__name__)


def holidays(cfg: Config) -> set[date]:
    return {date.fromisoformat(d) for d in cfg.runtime.holidays}


def is_due(now: datetime, last_attempt: str | None, cfg: Config) -> bool:
    """True once per trading day, after run_after_ist, if today has not been attempted."""
    now = now.astimezone(IST)
    today = now.date()
    if today.weekday() >= 5 or today in holidays(cfg):
        return False
    hh, mm = (int(x) for x in cfg.runtime.run_after_ist.split(":"))
    if now.time() < time(hh, mm):
        return False
    return last_attempt != today.isoformat()


def expected_today(now: datetime, cfg: Config) -> date:
    return expected_last_trading_day(now.astimezone(IST).date(), holidays(cfg))


def scheduler_loop(
    run_once: Callable[[date], object],
    get_last_attempt: Callable[[], str | None],
    set_last_attempt: Callable[[str], None],
    cfg: Config,
    stop: threading.Event,
    on_error: Callable[[str], None] | None = None,
    poll_seconds: float = 60.0,
) -> None:
    while not stop.is_set():
        now = datetime.now(IST)
        if is_due(now, get_last_attempt(), cfg):
            set_last_attempt(now.date().isoformat())
            try:
                run_once(expected_today(now, cfg))
            except Exception as exc:  # a failed run must alert, never kill the loop
                log.exception("daily run failed")
                if on_error:
                    on_error(f"daily run failed: {type(exc).__name__}: {exc}")
        stop.wait(poll_seconds)
