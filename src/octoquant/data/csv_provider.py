"""CSV import: one file per symbol plus INDEX.csv (broker or vendor exports)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from octoquant.data.base import DataPanel, finalize_panel

_ALIASES = {
    "date": "date", "timestamp": "date", "open": "open", "high": "high", "low": "low",
    "close": "close", "volume": "volume", "vwap": "vwap",
    "delivery %": "delivery_pct", "delivery_pct": "delivery_pct", "deliv_per": "delivery_pct",
}


def normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    renamed = {c: _ALIASES[c.strip().lower()] for c in df.columns if c.strip().lower() in _ALIASES}
    return df.rename(columns=renamed)


class CSVProvider:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def load(self, symbols: list[str], start: str, end: str | None) -> DataPanel:
        frames = []
        for sym in symbols:
            path = self.directory / f"{sym}.csv"
            if not path.exists():
                continue
            df = normalise_columns(pd.read_csv(path))
            df["symbol"] = sym
            frames.append(df)
        if not frames:
            raise FileNotFoundError(f"no symbol CSVs found in {self.directory}")
        index_path = self.directory / "INDEX.csv"
        if not index_path.exists():
            raise FileNotFoundError(f"missing {index_path}")
        stocks = pd.concat(frames, ignore_index=True)
        index = normalise_columns(pd.read_csv(index_path))
        return finalize_panel(*_clip(stocks, index, start, end), source="csv")


def _clip(stocks: pd.DataFrame, index: pd.DataFrame, start: str, end: str | None):
    for df in (stocks, index):
        df["date"] = pd.to_datetime(df["date"])
    lo = pd.Timestamp(start)
    hi = pd.Timestamp(end) if end else pd.Timestamp.max
    return (
        stocks[(stocks["date"] >= lo) & (stocks["date"] <= hi)],
        index[(index["date"] >= lo) & (index["date"] <= hi)],
    )
