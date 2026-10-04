"""State engine: packs the market into one compact, point-in-time snapshot per symbol and day.

Every feature at date t uses only data up to and including the close of t. Labels look forward
and exist only to train models; the walk-forward driver embargoes them so they never leak.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from octoquant.config import CostConfig, ModelConfig
from octoquant.costs import round_trip_cost_pct
from octoquant.data.base import DataPanel

FEATURE_COLUMNS = [
    "ret_1", "ret_5", "ret_10", "ret_20", "ret_60", "vol_20", "vol_60", "atr_pct",
    "trend_slope", "dist_sma50", "dist_high_252", "vwap_gap", "vol_z", "deliv_pct", "deliv_z",
    "clv", "gap", "rs_20", "idx_ret_5", "idx_ret_20", "idx_vol_20", "idx_dist_sma50",
    "breadth_50",
]
MARKET_FEATURE_COLUMNS = ["idx_ret_5", "idx_ret_20", "idx_ret_60", "idx_vol_20", "idx_dist_sma50",
                          "breadth_50"]


def _symbol_features(df: pd.DataFrame) -> pd.DataFrame:
    c, o, h, low = df["close"], df["open"], df["high"], df["low"]
    v, vw, dl = df["volume"], df["vwap"], df["delivery_pct"]
    out = pd.DataFrame({"date": df["date"], "symbol": df["symbol"]})
    ret1 = c.pct_change()
    for n in (1, 5, 10, 20, 60):
        out[f"ret_{n}"] = c.pct_change(n)
    out["vol_20"] = ret1.rolling(20).std()
    out["vol_60"] = ret1.rolling(60).std()
    prev = c.shift()
    tr = pd.concat([h - low, (h - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    out["atr_pct"] = tr.rolling(14).mean() / c
    ema10 = c.ewm(span=10, adjust=False).mean()
    ema50 = c.ewm(span=50, adjust=False).mean()
    out["trend_slope"] = (ema10 / ema50 - 1).where(c.expanding().count() >= 50)
    out["dist_sma50"] = c / c.rolling(50).mean() - 1
    out["dist_high_252"] = c / c.rolling(252, min_periods=120).max() - 1
    out["vwap_gap"] = c / vw - 1
    vm, vs = v.rolling(20).mean(), v.rolling(20).std()
    out["vol_z"] = (v - vm) / vs.replace(0, np.nan)
    out["deliv_pct"] = dl
    dm, ds = dl.rolling(60).mean(), dl.rolling(60).std()
    out["deliv_z"] = (dl - dm) / ds.replace(0, np.nan)
    rng = (h - low).replace(0, np.nan)
    out["clv"] = (((c - low) - (h - c)) / rng).fillna(0.0)
    out["gap"] = o / prev - 1
    return out


def market_features(index: pd.DataFrame, breadth: pd.Series) -> pd.DataFrame:
    idx = index.sort_values("date").set_index("date")
    c = idx["close"]
    ret1 = c.pct_change()
    m = pd.DataFrame(index=idx.index)
    m["idx_ret_5"] = c.pct_change(5)
    m["idx_ret_20"] = c.pct_change(20)
    m["idx_ret_60"] = c.pct_change(60)
    m["idx_vol_20"] = ret1.rolling(20).std()
    m["idx_dist_sma50"] = c / c.rolling(50).mean() - 1
    m["breadth_50"] = breadth.reindex(m.index)
    return m


def build_features(panel: DataPanel) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (stock_features, market_features). stock_features carries market columns too."""
    parts = [
        _symbol_features(g.sort_values("date"))
        for _, g in panel.stocks.groupby("symbol", sort=True)
    ]
    stock = pd.concat(parts, ignore_index=True)
    breadth = (
        stock.assign(above=(stock["dist_sma50"] > 0).where(stock["dist_sma50"].notna()))
        .groupby("date")["above"]
        .mean()
    )
    mkt = market_features(panel.index, breadth)
    stock = stock.merge(mkt.reset_index(), on="date", how="left")
    stock["rs_20"] = stock["ret_20"] - stock["idx_ret_20"]
    stock = stock.sort_values(["date", "symbol"]).reset_index(drop=True)
    return stock, mkt


def build_labels(
    panel: DataPanel, features: pd.DataFrame, cfg: ModelConfig, costs: CostConfig
) -> pd.DataFrame:
    """Forward-looking training targets per (date, symbol). NaN where the future is unseen."""
    H, R = cfg.label_horizon, cfg.risk_horizon
    rt_cost = round_trip_cost_pct(costs)
    vol = features.set_index(["date", "symbol"])["vol_20"]
    vol60 = features.set_index(["date", "symbol"])["vol_60"]
    parts = []
    for sym, g in panel.stocks.groupby("symbol", sort=True):
        g = g.sort_values("date")
        c, o, v, vw = g["close"], g["open"], g["volume"], g["vwap"]
        ret1 = c.pct_change()
        fwd = c.shift(-H) / o.shift(-1) - 1
        fwd_vol = ret1.rolling(R).std().shift(-R)
        vol_ma = v.rolling(20).mean()
        bp = ((c.shift(-1) > vw.shift(-1)) & (v.shift(-1) > vol_ma)).astype(float)
        bp = bp.where(c.shift(-1).notna() & vw.shift(-1).notna())
        parts.append(
            pd.DataFrame(
                {"date": g["date"].values, "symbol": sym, "fwd_ret": fwd.values,
                 "fwd_vol": fwd_vol.values, "y_bp": bp.values}
            )
        )
    lab = pd.concat(parts, ignore_index=True)
    key = pd.MultiIndex.from_frame(lab[["date", "symbol"]])
    v20 = vol.reindex(key).to_numpy()
    v60 = vol60.reindex(key).to_numpy()
    band = cfg.band_k * v20 * np.sqrt(H) + rt_cost
    f = lab["fwd_ret"].to_numpy()
    ydir = np.where(f > band, 2.0, np.where(f < -band, 0.0, 1.0))
    lab["y_dir"] = np.where(np.isnan(f) | np.isnan(band), np.nan, ydir)
    z = f / (v20 * np.sqrt(H))
    lab["z"] = z
    rank = lab.groupby("date")["z"].rank(pct=True)
    lab["y_sq"] = np.where(np.isnan(z), np.nan, (rank >= 2 / 3).astype(float))
    ratio = lab["fwd_vol"].to_numpy() / v60
    yr = np.where(ratio < 0.8, 0.0, np.where(ratio > 1.3, 2.0, 1.0))
    lab["y_risk"] = np.where(np.isnan(ratio), np.nan, yr)
    return lab.drop(columns=["z"])


def build_regime_labels(index: pd.DataFrame, cfg: ModelConfig) -> pd.Series:
    """0 bear, 1 chop, 2 bull: forward index trend scaled by trailing volatility."""
    idx = index.sort_values("date").set_index("date")
    c = idx["close"]
    L = cfg.regime_horizon
    fwd = c.shift(-L) / c - 1
    z = fwd / (c.pct_change().rolling(20).std() * np.sqrt(L))
    y = pd.Series(np.where(z < -0.5, 0.0, np.where(z > 0.5, 2.0, 1.0)), index=idx.index)
    return y.where(z.notna())


def snapshot(features: pd.DataFrame, date: pd.Timestamp, symbol: str) -> dict[str, float]:
    """The compact, numeric state a model sees for one symbol on one day."""
    row = features[(features["date"] == date) & (features["symbol"] == symbol)]
    if row.empty:
        raise KeyError(f"no snapshot for {symbol} on {date.date()}")
    return {k: round(float(row.iloc[0][k]), 6) for k in FEATURE_COLUMNS}
