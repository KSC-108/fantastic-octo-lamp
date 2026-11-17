"""Option chains: historical NSE bhavcopy data, or a Black-Scholes model chain on an underlying.

Every lookup is point-in-time: a price for day t uses only data published by the close of t.
Prices are per unit of underlying; multiply by the lot size for rupees.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from pathlib import Path

import numpy as np
import pandas as pd

from octoquant.config import OptionsConfig
from octoquant.options.pricing import bs_price, implied_vol

KINDS = ("CE", "PE")
OPEN_OFFSET_DAYS = (15.5 - 9.25) / 24.0  # 09:15 open is this much earlier than the 15:30 close


def year_frac(date: pd.Timestamp, expiry: pd.Timestamp, at_open: bool = False) -> float:
    """Calendar time to the 15:30 expiry, in years."""
    days = (expiry - date).days + (OPEN_OFFSET_DAYS if at_open else 0.0)
    return max(days, 0.0) / 365.0


class OptionChain:
    """Interface shared by both chains. Subclasses fill `_underlying` and implement `price`/`iv`."""

    name = "base"
    cfg: OptionsConfig
    _underlying: pd.DataFrame  # index: date; columns open, close

    @property
    def dates(self) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(self._underlying.index)

    def spot(self, date: pd.Timestamp, at_open: bool = False) -> float:
        return float(self._underlying.at[date, "open" if at_open else "close"])

    def expiries(self, date: pd.Timestamp) -> list[pd.Timestamp]:
        raise NotImplementedError

    def strikes(self, date: pd.Timestamp, expiry: pd.Timestamp) -> np.ndarray:
        raise NotImplementedError

    def price(self, date, expiry, strike, kind, at_open: bool = False) -> float | None:
        raise NotImplementedError

    def iv(self, date, expiry, strike, kind) -> float | None:
        raise NotImplementedError

    def atm_iv(self, date: pd.Timestamp) -> float | None:
        exps = [e for e in self.expiries(date) if (e - date).days >= 1]
        if not exps:
            return None
        e = exps[0]
        k = self.nearest_strike(date, e, self.spot(date))
        if k is None:
            return None
        vals = [v for v in (self.iv(date, e, k, "CE"), self.iv(date, e, k, "PE")) if v]
        return float(np.mean(vals)) if vals else None

    def nearest_strike(self, date, expiry, target: float) -> float | None:
        ks = self.strikes(date, expiry)
        if len(ks) == 0:
            return None
        return float(ks[np.argmin(np.abs(ks - target))])

    def settlement(self, expiry: pd.Timestamp) -> float:
        """Index options are cash-settled at the underlying's close on expiry day."""
        return self.spot(expiry)

    def truncate(self, last: pd.Timestamp) -> OptionChain:
        raise NotImplementedError


# ---- model chain --------------------------------------------------------------------------------
def _expiry_calendar(dates: pd.DatetimeIndex, weekday: int, cycle: str) -> list[pd.Timestamp]:
    """Nominal expiry weekday each week (or last one each month), rolled back to the previous
    trading day when it is a holiday. Weeks past the data keep the nominal date."""
    trading = set(dates)
    lo, hi = dates.min(), dates.max() + pd.Timedelta(days=70)
    nominal = pd.date_range(lo, hi, freq=f"W-{['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'][weekday]}")
    if cycle == "monthly":
        nominal = pd.DatetimeIndex(pd.Series(nominal).groupby(nominal.to_period("M")).max().values)
    out = []
    for d in nominal:
        if d <= dates.max():
            back = d
            while back not in trading and back > lo:
                back -= pd.Timedelta(days=1)
            if back in trading and back >= d - pd.Timedelta(days=4):
                out.append(back)
        else:
            out.append(d)
    return sorted(set(out))


class ModelChain(OptionChain):
    """Black-Scholes prices on a real (or synthetic) underlying.

    Volatility: the underlying's `vix` column (India VIX, in percent) when present, else 20-day
    realised volatility x `iv_multiplier`. Both are known at the close of day t. An open-of-day
    price uses the previous close's volatility.

    Limits, stated plainly: no traded premia, no skew unless `skew` is set, no bid-ask beyond the
    configured slippage. With iv_multiplier > 1 you are ASSUMING a variance risk premium, which
    flatters premium-selling strategies. Treat results as a sanity check, not evidence.
    """

    name = "model"

    def __init__(self, underlying: pd.DataFrame, cfg: OptionsConfig):
        u = underlying.copy()
        u["date"] = pd.to_datetime(u["date"]).dt.normalize()
        u = u.drop_duplicates("date").set_index("date").sort_index()
        if "open" not in u:
            u["open"] = u["close"]
        if "vix" in u and u["vix"].notna().any():
            vol = u["vix"].astype(float).ffill() / 100.0
            self.vol_source = "India VIX column"
        else:
            rv = np.log(u["close"]).diff().rolling(20, min_periods=10).std() * math.sqrt(252)
            vol = rv * cfg.iv_multiplier
            self.vol_source = f"20-day realised vol x {cfg.iv_multiplier:g}"
        u["sigma"] = vol.clip(lower=cfg.iv_floor).bfill().fillna(0.15)
        u["sigma_open"] = u["sigma"].shift(1).fillna(u["sigma"])
        self._underlying = u
        self.cfg = cfg
        self._expiries = _expiry_calendar(self.dates, cfg.expiry_weekday, cfg.expiry_cycle)

    def truncate(self, last):
        c = object.__new__(ModelChain)
        c.__dict__.update(self.__dict__)
        c._underlying = self._underlying[self._underlying.index <= last]
        return c

    def expiries(self, date):
        return [e for e in self._expiries if e >= date][:6]

    def strikes(self, date, expiry):
        s, step = self.spot(date), self.cfg.strike_step
        return np.arange(math.floor(s * 0.7 / step), math.ceil(s * 1.3 / step) + 1) * step

    def _sigma(self, date, strike, at_open):
        atm = float(self._underlying.at[date, "sigma_open" if at_open else "sigma"])
        if self.cfg.skew:
            s = self.spot(date, at_open)
            atm *= max(0.3, 1.0 - self.cfg.skew * math.log(strike / s))
        return atm

    def price(self, date, expiry, strike, kind, at_open=False):
        if date not in self._underlying.index or expiry < date:
            return None
        s = self.spot(date, at_open)
        t = year_frac(date, expiry, at_open)
        px = bs_price(s, strike, t, self._sigma(date, strike, at_open), kind,
                      self.cfg.risk_free, self.cfg.dividend_yield)
        return max(round(float(px) / 0.05) * 0.05, 0.05)

    def iv(self, date, expiry, strike, kind):
        return self._sigma(date, strike, False)


# ---- bhavcopy chain -----------------------------------------------------------------------------
_ALIASES = {
    # old F&O bhavcopy
    "instrument": "instrument", "symbol": "symbol", "expiry_dt": "expiry", "strike_pr": "strike",
    "option_typ": "kind", "open": "open", "close": "close", "settle_pr": "settle",
    "open_int": "oi", "timestamp": "date", "contracts": "volume",
    # UDiFF (NSE, July 2024 onward)
    "traddt": "date", "fininstrmtp": "instrument", "tckrsymb": "symbol", "xprydt": "expiry",
    "strkpric": "strike", "optntp": "kind", "opnpric": "open", "clspric": "close",
    "sttlmpric": "settle", "opnintrst": "oi", "undrlygpric": "underlying", "ttltradgvol": "volume",
    # generic exports
    "date": "date", "expiry": "expiry", "expiry_date": "expiry", "strike": "strike",
    "strike_price": "strike", "option_type": "kind", "type": "kind", "right": "kind",
    "settle": "settle", "oi": "oi", "underlying": "underlying", "spot": "underlying",
    "underlying_value": "underlying", "volume": "volume", "ltp": "close",
}
_OPTION_INSTRUMENTS = {"OPTIDX", "IDO", "OPTSTK", "STO"}


def load_bhavcopy(paths: Iterable[str | Path], symbol: str = "NIFTY") -> pd.DataFrame:
    """Read NSE F&O bhavcopy CSVs (old or UDiFF format, or a generic chain export) into one
    standard frame: date, expiry, strike, kind, open, close, settle, oi, volume, underlying."""
    frames = []
    for p in paths:
        raw = pd.read_csv(p, skipinitialspace=True)
        cols = {c: _ALIASES[c.strip().lower()] for c in raw.columns if c.strip().lower() in _ALIASES}
        df = raw.rename(columns=cols)
        df = df.loc[:, ~df.columns.duplicated()]
        if "instrument" in df:
            df = df[df["instrument"].astype(str).str.strip().str.upper().isin(_OPTION_INSTRUMENTS)]
        if "symbol" in df:
            df = df[df["symbol"].astype(str).str.strip().str.upper() == symbol.upper()]
        missing = {"date", "expiry", "strike", "kind", "close"} - set(df.columns)
        if missing:
            raise ValueError(f"{p}: missing columns {sorted(missing)}")
        frames.append(df)
    if not frames:
        raise FileNotFoundError("no bhavcopy files given")
    df = pd.concat(frames, ignore_index=True)
    out = pd.DataFrame({
        "date": pd.to_datetime(df["date"], dayfirst=True, format="mixed").dt.normalize(),
        "expiry": pd.to_datetime(df["expiry"], dayfirst=True, format="mixed").dt.normalize(),
        "strike": pd.to_numeric(df["strike"], errors="coerce"),
        "kind": df["kind"].astype(str).str.strip().str.upper()
        .replace({"CALL": "CE", "PUT": "PE", "C": "CE", "P": "PE"}),
    })
    for c in ("open", "close", "settle", "oi", "volume", "underlying"):
        out[c] = pd.to_numeric(df[c], errors="coerce") if c in df else np.nan
    out = out[out["kind"].isin(KINDS) & out["strike"].notna() & (out["expiry"] >= out["date"])]
    return out.drop_duplicates(["date", "expiry", "strike", "kind"], keep="last") \
        .sort_values(["date", "expiry", "strike", "kind"]).reset_index(drop=True)


class BhavcopyChain(OptionChain):
    """Historical end-of-day option prices. A contract's price is its close, then its settlement
    price when it did not trade. The open is used for fills when it is positive, else the close.

    Spot comes from the bhavcopy's underlying column (UDiFF), else `underlying`, else put-call
    parity at the strike where |call - put| is smallest on the nearest expiry (approximate)."""

    name = "bhavcopy"

    def __init__(self, chain: pd.DataFrame, cfg: OptionsConfig, underlying: pd.DataFrame | None = None,
                 max_dte: int = 70):
        self.cfg = cfg
        c = chain[(chain["expiry"] - chain["date"]).dt.days <= max_dte].copy()
        c["mark"] = c["close"].where(c["close"] > 0, c["settle"])
        c = c[c["mark"] > 0]
        c["open_px"] = c["open"].where(c["open"] > 0, c["mark"])
        self._chain = c
        self._px = {(r.date, r.expiry, float(r.strike), r.kind): (float(r.open_px), float(r.mark))
                    for r in c.itertuples(index=False)}
        self._strikes = {k: np.sort(g["strike"].unique().astype(float))
                         for k, g in c.groupby(["date", "expiry"])}
        self._exp = {d: sorted(g["expiry"].unique()) for d, g in c.groupby("date")}
        self._underlying = self._build_underlying(c, underlying)
        self._iv_cache: dict = {}

    def _build_underlying(self, c, underlying):
        if underlying is not None:
            u = underlying.copy()
            u["date"] = pd.to_datetime(u["date"]).dt.normalize()
            u = u.set_index("date").sort_index()[["open", "close"]]
            u = u[u.index.isin(c["date"].unique())]
            self.spot_source = "underlying CSV"
            return u
        if c["underlying"].notna().any():
            s = c.groupby("date")["underlying"].median()
            self.spot_source = "bhavcopy underlying column"
        else:
            vals = {}
            for d, g in c.groupby("date"):
                near = g[g["expiry"] == g["expiry"].min()]
                piv = near.pivot_table(index="strike", columns="kind", values="mark")
                piv = piv.dropna()
                if piv.empty:
                    continue
                k = (piv["CE"] - piv["PE"]).abs().idxmin()
                vals[d] = float(k + piv.at[k, "CE"] - piv.at[k, "PE"])
            s = pd.Series(vals)
            self.spot_source = "put-call parity (approximate)"
        # Bhavcopies carry no index open: the previous close stands in, the conservative choice
        # being that the decision never sees the day's open before it is fixed.
        return pd.DataFrame({"open": s.shift(1).fillna(s), "close": s}).sort_index()

    def truncate(self, last):
        c = object.__new__(BhavcopyChain)
        c.__dict__.update(self.__dict__)
        c._underlying = self._underlying[self._underlying.index <= last]
        return c

    def expiries(self, date):
        return list(self._exp.get(date, []))

    def strikes(self, date, expiry):
        return self._strikes.get((date, expiry), np.array([]))

    def price(self, date, expiry, strike, kind, at_open=False):
        if date > self.dates.max():
            return None
        hit = self._px.get((date, expiry, float(strike), kind))
        if hit is None:
            return None
        return hit[0] if at_open else hit[1]

    def iv(self, date, expiry, strike, kind):
        key = (date, expiry, float(strike), kind)
        if key not in self._iv_cache:
            px = self.price(date, expiry, strike, kind)
            self._iv_cache[key] = None if px is None else implied_vol(
                px, self.spot(date), strike, year_frac(date, expiry), kind,
                self.cfg.risk_free, self.cfg.dividend_yield)
        return self._iv_cache[key]


def build_chain(cfg, panel_index: pd.DataFrame | None = None) -> OptionChain:
    """Chain from config. `panel_index` is the index frame of the equity data source, used as the
    model chain's underlying when no options.underlying_csv is set."""
    o = cfg.options
    und = pd.read_csv(o.underlying_csv) if o.underlying_csv else None
    if und is not None:
        und.columns = [c.strip().lower() for c in und.columns]
    if o.source == "bhavcopy":
        files = sorted(Path(o.chain_dir).glob("*.csv"))
        if not files:
            raise FileNotFoundError(f"no bhavcopy CSVs in {o.chain_dir}")
        return BhavcopyChain(load_bhavcopy(files, o.underlying), o, und)
    if und is None:
        if panel_index is None:
            raise ValueError("model chain needs options.underlying_csv or an index from data.source")
        und = panel_index
    return ModelChain(und, o)
