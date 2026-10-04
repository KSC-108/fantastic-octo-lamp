"""Synthetic NSE-like market for tests and demos.

NOT real data. A latent per-stock 'flow' variable drives delivery %, close location and,
when `edge` > 0, a small amount of next-day return. With edge = 0 the market has no
exploitable structure, which lets us verify that the research harness rejects noise.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from octoquant.config import DEFAULT_SYMBOLS
from octoquant.data.base import DataPanel, finalize_panel

# (daily drift, daily vol) for bull, chop, bear
_REGIMES = [(0.0010, 0.007), (0.0001, 0.009), (-0.0012, 0.015)]
_STAY = [0.985, 0.97, 0.97]


def _market_path(n: int, rng: np.random.Generator) -> np.ndarray:
    state = 1
    out = np.empty(n)
    for t in range(n):
        mu, sig = _REGIMES[state]
        out[t] = rng.normal(mu, sig)
        if rng.random() > _STAY[state]:
            others = [s for s in range(3) if s != state]
            state = int(rng.choice(others))
    return out


def generate_synthetic(
    symbols: list[str] | None = None,
    years: float = 9.0,
    start: str = "2016-01-04",
    seed: int = 1,
    edge: float = 0.001,
) -> DataPanel:
    rng = np.random.default_rng(seed)
    symbols = symbols or DEFAULT_SYMBOLS[:20]
    dates = pd.bdate_range(start, periods=int(years * 252))
    n = len(dates)
    market = _market_path(n, rng)

    frames = []
    rets = np.zeros((len(symbols), n))
    gaps = np.zeros((len(symbols), n))
    for i, sym in enumerate(symbols):
        beta = rng.uniform(0.6, 1.4)
        idio = rng.uniform(0.008, 0.016)
        flow = np.zeros(n)
        for t in range(1, n):
            flow[t] = 0.7 * flow[t - 1] + np.sqrt(1 - 0.49) * rng.normal()
        r = beta * market + idio * rng.normal(size=n)
        r[1:] += edge * flow[:-1]
        r = np.clip(r, -0.18, 0.18)
        gap = np.clip(0.3 * idio * rng.normal(size=n), -0.05, 0.05)
        gap = np.where(np.abs(gap) > np.abs(r) * 1.5 + 0.01, r * 0.5, gap)

        close = rng.uniform(200, 3000) * np.cumprod(1 + r)
        prev = np.concatenate([[close[0] / (1 + r[0])], close[:-1]])
        open_ = prev * (1 + gap)
        u = np.clip(0.5 + 0.18 * flow + 0.25 * rng.normal(size=n), 0.02, 0.98)
        ext = np.abs(rng.normal(size=n)) * 0.010 + 0.002
        high = np.maximum(open_, close) * (1 + ext * u)
        low = np.minimum(open_, close) * (1 - ext * (1 - u))
        vwap = np.clip(
            (open_ + high + low + 2 * close) / 5 + 0.05 * (high - low) * rng.normal(size=n),
            low,
            high,
        )
        vol_z = np.zeros(n)
        for t in range(1, n):
            vol_z[t] = 0.5 * vol_z[t - 1] + np.sqrt(0.75) * rng.normal()
        base = rng.uniform(1e6, 8e6)
        volume = base * np.exp(0.25 * vol_z + 0.5 * np.abs(r) / idio)
        delivery = np.clip(45 + 8 * flow + 3 * rng.normal(size=n), 5, 95)

        rets[i], gaps[i] = r, gap
        frames.append(
            pd.DataFrame(
                {
                    "date": dates, "symbol": sym, "open": open_, "high": high, "low": low,
                    "close": close, "volume": volume.round(), "vwap": vwap,
                    "delivery_pct": delivery,
                }
            )
        )

    stocks = pd.concat(frames, ignore_index=True)
    idx_ret = rets.mean(axis=0)
    idx_gap = gaps.mean(axis=0)
    idx_close = 10000 * np.cumprod(1 + idx_ret)
    prev = np.concatenate([[idx_close[0] / (1 + idx_ret[0])], idx_close[:-1]])
    idx_open = prev * (1 + idx_gap)
    index = pd.DataFrame(
        {
            "date": dates,
            "open": idx_open,
            "high": np.maximum(idx_open, idx_close) * 1.002,
            "low": np.minimum(idx_open, idx_close) * 0.998,
            "close": idx_close,
        }
    )
    return finalize_panel(stocks, index, source="synthetic")
