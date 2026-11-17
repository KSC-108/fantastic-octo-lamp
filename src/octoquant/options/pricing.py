"""Black-Scholes pricing, greeks and implied volatility for European options.

NSE index options are European and cash-settled, so Black-Scholes with a continuous dividend
yield is the standard first approximation. It has no volatility skew: real OTM puts trade richer.
"""

from __future__ import annotations

import math

import numpy as np

SQRT2 = math.sqrt(2.0)


def _ncdf(x):
    return 0.5 * (1.0 + _erf(np.asarray(x, dtype=float) / SQRT2))


def _erf(x):
    # numpy has no vectorised erf; math.erf is exact, so vectorise it.
    return np.vectorize(math.erf, otypes=[float])(x)


def _npdf(x):
    x = np.asarray(x, dtype=float)
    return np.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def _d1d2(s, k, t, r, q, sigma):
    vt = sigma * np.sqrt(t)
    d1 = (np.log(s / k) + (r - q + 0.5 * sigma * sigma) * t) / vt
    return d1, d1 - vt


def bs_price(s, k, t, sigma, kind: str, r: float = 0.065, q: float = 0.0):
    """Premium per unit of underlying. kind is 'CE' or 'PE'. t in years.

    At t <= 0 or sigma <= 0 the option is worth its (discounted-forward) intrinsic value.
    """
    s, k, t, sigma = (np.asarray(v, dtype=float) for v in (s, k, t, sigma))
    call = kind.upper() in ("CE", "C", "CALL")
    intrinsic = np.maximum(s - k, 0.0) if call else np.maximum(k - s, 0.0)
    live = (t > 0) & (sigma > 0)
    if not np.any(live):
        return intrinsic if intrinsic.ndim else float(intrinsic)
    tt, ss = np.where(live, t, 1.0), np.where(live, sigma, 0.2)
    d1, d2 = _d1d2(s, k, tt, r, q, ss)
    df_r, df_q = np.exp(-r * tt), np.exp(-q * tt)
    if call:
        px = s * df_q * _ncdf(d1) - k * df_r * _ncdf(d2)
    else:
        px = k * df_r * _ncdf(-d2) - s * df_q * _ncdf(-d1)
    out = np.where(live, np.maximum(px, 0.0), intrinsic)
    return out if out.ndim else float(out)


def bs_greeks(s, k, t, sigma, kind: str, r: float = 0.065, q: float = 0.0) -> dict:
    """Delta, gamma, vega (per 1 vol point), theta (per calendar day), per unit of underlying."""
    call = kind.upper() in ("CE", "C", "CALL")
    if t <= 0 or sigma <= 0:
        itm = (s > k) if call else (s < k)
        return {"delta": (1.0 if call else -1.0) if itm else 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0}
    d1, d2 = _d1d2(s, k, t, r, q, sigma)
    d1, d2 = float(d1), float(d2)
    df_r, df_q = math.exp(-r * t), math.exp(-q * t)
    pdf = float(_npdf(d1))
    n = lambda x: float(_ncdf(x))  # noqa: E731
    gamma = df_q * pdf / (s * sigma * math.sqrt(t))
    vega = s * df_q * pdf * math.sqrt(t) / 100.0
    common = -s * df_q * pdf * sigma / (2 * math.sqrt(t))
    if call:
        delta = df_q * n(d1)
        theta = common - r * k * df_r * n(d2) + q * s * df_q * n(d1)
    else:
        delta = -df_q * n(-d1)
        theta = common + r * k * df_r * n(-d2) - q * s * df_q * n(-d1)
    return {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta / 365.0}


def implied_vol(price: float, s: float, k: float, t: float, kind: str, r: float = 0.065,
                q: float = 0.0, lo: float = 1e-4, hi: float = 5.0, tol: float = 1e-6) -> float | None:
    """Bisection. Returns None when the price is outside the no-arbitrage range."""
    if t <= 0 or price <= 0:
        return None
    f = lambda v: bs_price(s, k, t, v, kind, r, q) - price  # noqa: E731
    flo, fhi = f(lo), f(hi)
    if flo > 0 or fhi < 0:
        return None
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        fm = f(mid)
        if abs(fm) < tol:
            return mid
        if fm > 0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)
