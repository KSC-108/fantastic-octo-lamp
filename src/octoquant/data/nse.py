"""NSE daily data through the public `jugaad-data` library (pip install octoquant[nse]).

IMPORTANT: this adapter has not been exercised against live NSE from the build environment,
whose egress policy blocks nseindia.com. Column mapping is verified against the library's own
header definitions; network behaviour must be confirmed from a host that can reach NSE.
NSE can block datacenter IP ranges: keep the on-disk cache and fetch incrementally.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from octoquant.data.base import STOCK_COLUMNS, DataPanel, finalize_panel

log = logging.getLogger(__name__)

_STOCK_MAP = {
    "DATE": "date", "OPEN": "open", "HIGH": "high", "LOW": "low", "CLOSE": "close",
    "VWAP": "vwap", "VOLUME": "volume", "DELIVERY %": "delivery_pct", "SYMBOL": "symbol",
}
_INDEX_MAP = {
    "HistoricalDate": "date", "OPEN": "open", "HIGH": "high", "LOW": "low", "CLOSE": "close",
}


def normalise_nse_stock_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.rename(columns=_STOCK_MAP)
    if "series" in {c.lower() for c in out.columns}:
        out = out[out[[c for c in out.columns if c.lower() == "series"][0]] == "EQ"]
    out = out[[c for c in STOCK_COLUMNS if c in out.columns]].copy()
    out["date"] = pd.to_datetime(out["date"])
    for col in ("open", "high", "low", "close", "volume", "vwap", "delivery_pct"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out.dropna(subset=["open", "high", "low", "close"])


def normalise_nse_index_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.rename(columns=_INDEX_MAP)[["date", "open", "high", "low", "close"]].copy()
    out["date"] = pd.to_datetime(out["date"])
    for col in ("open", "high", "low", "close"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out.dropna()


class NSEProvider:
    def __init__(self, cache_dir: str | Path, index_name: str = "NIFTY 50", max_failure_share=0.2):
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.index_name = index_name
        self.max_failure_share = max_failure_share

    def _fetch_stock(self, symbol: str, lo: date, hi: date) -> pd.DataFrame:
        from jugaad_data.nse import stock_df

        return normalise_nse_stock_frame(stock_df(symbol=symbol, from_date=lo, to_date=hi))

    def _fetch_index(self, lo: date, hi: date) -> pd.DataFrame:
        from jugaad_data.nse import index_df

        return normalise_nse_index_frame(index_df(self.index_name, lo, hi))

    def _incremental(self, path: Path, fetch, start: date, end: date) -> pd.DataFrame:
        cached = pd.read_csv(path, parse_dates=["date"]) if path.exists() else None
        lo = start
        if cached is not None and not cached.empty:
            lo = max(start, cached["date"].max().date() + timedelta(days=1))
        if lo <= end:
            fresh = fetch(lo, end)
            if cached is not None and not cached.empty:
                fresh = pd.concat([cached, fresh], ignore_index=True)
            cached = fresh.drop_duplicates("date", keep="last").sort_values("date")
            cached.to_csv(path, index=False)
        if cached is None:
            raise RuntimeError(f"no data for {path.stem}")
        return cached

    def load(self, symbols: list[str], start: str, end: str | None) -> DataPanel:
        lo = pd.Timestamp(start).date()
        hi = pd.Timestamp(end).date() if end else date.today()
        frames, failed = [], []
        for sym in symbols:
            try:
                df = self._incremental(
                    self.cache / f"{sym}.csv", lambda a, b, s=sym: self._fetch_stock(s, a, b), lo, hi
                )
                df = df.assign(symbol=sym)
                frames.append(df[(df["date"] >= pd.Timestamp(lo)) & (df["date"] <= pd.Timestamp(hi))])
            except Exception as exc:  # network, parsing, symbol not found
                log.warning("failed to load %s: %s", sym, exc)
                failed.append(sym)
        if len(failed) > self.max_failure_share * len(symbols):
            raise RuntimeError(f"too many symbol failures ({len(failed)}/{len(symbols)}): {failed}")
        index = self._incremental(self.cache / "INDEX.csv", self._fetch_index, lo, hi)
        index = index[(index["date"] >= pd.Timestamp(lo)) & (index["date"] <= pd.Timestamp(hi))]
        return finalize_panel(pd.concat(frames, ignore_index=True), index, source="nse")
