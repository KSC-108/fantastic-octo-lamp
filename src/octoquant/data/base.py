"""Shared market-data schema and validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

import pandas as pd

STOCK_COLUMNS = ["date", "symbol", "open", "high", "low", "close", "volume", "vwap", "delivery_pct"]
INDEX_COLUMNS = ["date", "open", "high", "low", "close"]


@dataclass
class DataPanel:
    """stocks: long frame sorted by (date, symbol). index: one row per date."""

    stocks: pd.DataFrame
    index: pd.DataFrame
    source: str = "unknown"

    @property
    def symbols(self) -> list[str]:
        return sorted(self.stocks["symbol"].unique())

    @property
    def dates(self) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(sorted(self.stocks["date"].unique()))

    def truncate(self, last_date: pd.Timestamp) -> DataPanel:
        """Point-in-time view: nothing after last_date is visible."""
        return DataPanel(
            self.stocks[self.stocks["date"] <= last_date].reset_index(drop=True),
            self.index[self.index["date"] <= last_date].reset_index(drop=True),
            self.source,
        )


class DataProvider(Protocol):
    def load(self, symbols: list[str], start: str, end: str | None) -> DataPanel: ...


def finalize_panel(stocks: pd.DataFrame, index: pd.DataFrame, source: str) -> DataPanel:
    stocks = stocks.copy()
    index = index.copy()
    for col in STOCK_COLUMNS:
        if col not in stocks.columns:
            stocks[col] = float("nan")
    stocks["date"] = pd.to_datetime(stocks["date"]).dt.normalize()
    index["date"] = pd.to_datetime(index["date"]).dt.normalize()
    stocks = stocks[STOCK_COLUMNS].sort_values(["date", "symbol"]).reset_index(drop=True)
    index = index[INDEX_COLUMNS].sort_values("date").reset_index(drop=True)
    validate_panel(stocks, index)
    return DataPanel(stocks, index, source)


def validate_panel(stocks: pd.DataFrame, index: pd.DataFrame) -> None:
    """Fail loudly on malformed data: silent bad data is how backtests lie."""
    if stocks.empty or index.empty:
        raise ValueError("empty market data")
    if stocks.duplicated(["date", "symbol"]).any():
        raise ValueError("duplicate (date, symbol) rows")
    if index.duplicated("date").any():
        raise ValueError("duplicate index dates")
    px = stocks[["open", "high", "low", "close"]]
    if (px <= 0).any().any() or px.isna().any().any():
        raise ValueError("non-positive or missing prices")
    bad = (
        (stocks["high"] < stocks[["open", "close", "low"]].max(axis=1) - 1e-9)
        | (stocks["low"] > stocks[["open", "close", "high"]].min(axis=1) + 1e-9)
    )
    if bad.any():
        raise ValueError(f"{int(bad.sum())} rows violate high/low bounds")


def expected_last_trading_day(as_of: date, holidays: set[date] | None = None) -> date:
    """Most recent weekday on or before as_of that is not a configured holiday."""
    holidays = holidays or set()
    d = as_of
    while d.weekday() >= 5 or d in holidays:
        d -= timedelta(days=1)
    return d
