"""Telegram alerts through a BotFather bot. Never raises, never logs the token."""

from __future__ import annotations

import logging
import os

import httpx

log = logging.getLogger(__name__)
LEVEL_TAG = {"info": "INFO", "warn": "WARNING", "critical": "CRITICAL"}


class Notifier:
    def __init__(self, token: str | None = None, chat_id: str | None = None,
                 client: httpx.Client | None = None):
        self.token = token if token is not None else os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id if chat_id is not None else os.environ.get("TELEGRAM_CHAT_ID", "")
        self.client = client
        self.sent: list[str] = []  # in-process record, useful for tests and the dashboard

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def _redact(self, text: str) -> str:
        return text.replace(self.token, "***") if self.token else text

    def send(self, text: str, level: str = "info") -> bool:
        message = f"[OctoQuant paper] {LEVEL_TAG.get(level, 'INFO')}: {text}"
        self.sent.append(message)
        if not self.enabled:
            return False
        try:
            client = self.client or httpx.Client(timeout=10)
            resp = client.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": self.chat_id, "text": message[:4000]},
            )
            return resp.status_code == 200
        except Exception as exc:  # alerts must never take the trading loop down
            log.warning("telegram send failed: %s", self._redact(str(exc)))
            return False
