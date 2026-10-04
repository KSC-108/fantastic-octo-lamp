"""SQLite persistence: decisions, fills, trades, equity, events and the simulator's state.

Every decision is logged with its eventual outcome so calibration can be measured on live data.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY, date TEXT NOT NULL, symbol TEXT NOT NULL,
  p_up REAL, p_bp REAL, sq REAL, p_bear REAL, p_stressed REAL,
  fired INTEGER, size_frac REAL, action TEXT, band REAL, snapshot TEXT,
  fwd_ret REAL, y_up INTEGER, resolved INTEGER DEFAULT 0,
  UNIQUE(date, symbol)
);
CREATE TABLE IF NOT EXISTS fills (
  id INTEGER PRIMARY KEY, date TEXT, symbol TEXT, side TEXT, shares INTEGER,
  price REAL, costs REAL, reason TEXT
);
CREATE TABLE IF NOT EXISTS trades (
  id INTEGER PRIMARY KEY, symbol TEXT, entry_date TEXT, exit_date TEXT, shares INTEGER,
  entry_px REAL, exit_px REAL, pnl REAL, ret REAL, days INTEGER, reason TEXT, p_up REAL,
  decided TEXT
);
CREATE TABLE IF NOT EXISTS equity (
  date TEXT PRIMARY KEY, equity REAL, cash REAL, exposure REAL, drawdown REAL
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, ts TEXT, level TEXT, message TEXT
);
CREATE TABLE IF NOT EXISTS held_orders (
  id INTEGER PRIMARY KEY, date TEXT, symbol TEXT, notional REAL, atr_pct REAL,
  p_up REAL, p_win REAL, status TEXT DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS rules (
  id INTEGER PRIMARY KEY, ts TEXT, param TEXT, old_value REAL, new_value REAL,
  rationale TEXT, source TEXT, accepted INTEGER, detail TEXT
);
"""


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._mem = sqlite3.connect(":memory:", check_same_thread=False) \
            if self.path == ":memory:" else None
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        with self._lock:
            conn = self._mem or sqlite3.connect(self.path, timeout=30)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            finally:
                if self._mem is None:
                    conn.close()

    # ---- key/value -------------------------------------------------------------------------
    def get(self, key: str, default=None):
        with self._conn() as c:
            row = c.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set(self, key: str, value) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET "
                      "value=excluded.value", (key, json.dumps(value)))

    # ---- writes ----------------------------------------------------------------------------
    def log_event(self, level: str, message: str) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO events(ts,level,message) VALUES(?,?,?)",
                      (datetime.now(UTC).isoformat(timespec="seconds"), level, message))

    def add_decisions(self, date: str, rows: list[dict], bands: dict[str, float],
                      snapshots: dict[str, dict]) -> None:
        with self._conn() as c:
            c.executemany(
                "INSERT OR REPLACE INTO decisions(date,symbol,p_up,p_bp,sq,p_bear,p_stressed,fired,"
                "size_frac,action,band,snapshot) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                [(date, r["symbol"], r["p_up"], r["p_bp"], r["sq"], r["p_bear"], r["p_stressed"],
                  int(r["fired"]), r["size_frac"], r["action"], bands.get(r["symbol"]),
                  json.dumps(snapshots[r["symbol"]]) if r["symbol"] in snapshots else None)
                 for r in rows])

    def add_fills(self, rows: list[dict]) -> None:
        with self._conn() as c:
            c.executemany(
                "INSERT INTO fills(date,symbol,side,shares,price,costs,reason) "
                "VALUES(:date,:symbol,:side,:shares,:price,:costs,:reason)", rows)

    def add_trades(self, rows: list[dict]) -> None:
        with self._conn() as c:
            c.executemany(
                "INSERT INTO trades(symbol,entry_date,exit_date,shares,entry_px,exit_px,pnl,ret,"
                "days,reason,p_up,decided) VALUES(:symbol,:entry_date,:exit_date,:shares,"
                ":entry_px,:exit_px,:pnl,:ret,:days,:reason,:p_up,:decided)", rows)

    def add_equity(self, date: str, equity: float, cash: float, exposure: float,
                   drawdown: float) -> None:
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO equity VALUES(?,?,?,?,?)",
                      (date, equity, cash, exposure, drawdown))

    def add_held_order(self, date: str, o: dict) -> int:
        with self._conn() as c:
            cur = c.execute(
                "INSERT INTO held_orders(date,symbol,notional,atr_pct,p_up,p_win) VALUES(?,?,?,?,?,?)",
                (date, o["symbol"], o["notional"], o["atr_pct"], o["p_up"], o["p_win"]))
            return int(cur.lastrowid)

    def set_held_status(self, order_id: int, status: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE held_orders SET status=? WHERE id=?", (status, order_id))

    def add_rule(self, param: str, old: float, new: float, rationale: str, source: str,
                 accepted: bool, detail: str) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO rules(ts,param,old_value,new_value,rationale,source,accepted,"
                      "detail) VALUES(?,?,?,?,?,?,?,?)",
                      (datetime.now(UTC).isoformat(timespec="seconds"), param, old, new,
                       rationale, source, int(accepted), detail))

    def resolve_decision(self, date: str, symbol: str, fwd_ret: float, y_up: int) -> None:
        with self._conn() as c:
            c.execute("UPDATE decisions SET fwd_ret=?, y_up=?, resolved=1 WHERE date=? AND symbol=?",
                      (fwd_ret, y_up, date, symbol))

    # ---- reads -----------------------------------------------------------------------------
    def frame(self, sql: str, params: tuple = ()) -> pd.DataFrame:
        with self._conn() as c:
            return pd.read_sql_query(sql, c, params=params)

    def equity_curve(self) -> pd.DataFrame:
        return self.frame("SELECT * FROM equity ORDER BY date")

    def recent_events(self, n: int = 30) -> list[dict]:
        df = self.frame("SELECT ts,level,message FROM events ORDER BY id DESC LIMIT ?", (n,))
        return df.to_dict("records")

    def trades(self, n: int | None = None) -> pd.DataFrame:
        sql = "SELECT * FROM trades ORDER BY id DESC" + (f" LIMIT {int(n)}" if n else "")
        return self.frame(sql)

    def latest_decisions(self) -> pd.DataFrame:
        return self.frame("SELECT * FROM decisions WHERE date=(SELECT MAX(date) FROM decisions) "
                          "ORDER BY fired DESC, p_up DESC")

    def unresolved_decisions(self, before: str) -> pd.DataFrame:
        return self.frame("SELECT * FROM decisions WHERE resolved=0 AND date<=? AND band IS NOT NULL",
                          (before,))

    def resolved_calibration_samples(self, last_n_days: int) -> pd.DataFrame:
        return self.frame(
            "SELECT p_up, y_up FROM decisions WHERE resolved=1 AND date >= "
            "(SELECT MIN(date) FROM (SELECT DISTINCT date FROM decisions WHERE resolved=1 "
            "ORDER BY date DESC LIMIT ?))", (last_n_days,))

    def paper_days(self) -> int:
        return int(self.frame("SELECT COUNT(*) AS n FROM equity")["n"].iloc[0])
