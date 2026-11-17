"""Typed configuration. Every tunable lives here; nothing is hard-coded in the engine."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

# Large, liquid NIFTY 50 names. Using today's constituents for past dates introduces
# survivorship bias, which flatters backtests. Treat historical results accordingly.
DEFAULT_SYMBOLS = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "HINDUNILVR", "ITC", "SBIN",
    "BHARTIARTL", "KOTAKBANK", "LT", "AXISBANK", "ASIANPAINT", "MARUTI", "SUNPHARMA",
    "TITAN", "ULTRACEMCO", "BAJFINANCE", "NESTLEIND", "WIPRO", "HCLTECH", "POWERGRID",
    "NTPC", "TATASTEEL", "TECHM", "ONGC", "JSWSTEEL", "COALINDIA", "CIPLA", "DRREDDY",
]


class UniverseConfig(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: list(DEFAULT_SYMBOLS))
    index: str = "NIFTY 50"


class DataConfig(BaseModel):
    source: Literal["synthetic", "csv", "nse"] = "synthetic"
    cache_dir: str = "data/cache"
    csv_dir: str = "data/csv"
    start: str = "2016-01-01"
    end: str | None = None


class ModelConfig(BaseModel):
    label_horizon: int = 5
    risk_horizon: int = 10
    regime_horizon: int = 20
    min_train_days: int = 504
    retrain_every: int = 63
    cal_frac: float = 0.2
    band_k: float = 0.5
    max_iter: int = 120
    seed: int = 7

    @property
    def embargo(self) -> int:
        """Rows whose labels look this far ahead must not be used to train a model at t."""
        return max(self.label_horizon, self.risk_horizon, self.regime_horizon) + 1


class CostConfig(BaseModel):
    """Indian delivery-equity costs. Rates are ASSUMPTIONS: verify against your contract note."""

    brokerage_pct: float = 0.0
    brokerage_flat: float = 0.0
    stt_pct: float = 0.001
    exchange_txn_pct: float = 0.0000297
    sebi_pct: float = 0.000001
    stamp_buy_pct: float = 0.00015
    gst_pct: float = 0.18
    dp_charge_sell: float = 13.5
    slippage_bps: float = 5.0


class RiskConfig(BaseModel):
    max_position_pct: float = 0.10
    max_positions: int = 8
    max_gross_pct: float = 0.80
    daily_loss_limit_pct: float = 0.02
    max_drawdown_pct: float = 0.15
    manual_approval_above: float = 250_000.0


class SizingConfig(BaseModel):
    kelly_fraction: float = 0.25
    min_p: float = 0.45
    payoff_floor: float = 0.5
    payoff_cap: float = 3.0


class StrategyParams(BaseModel):
    tau_dir: float = 0.35
    tau_bp: float = 0.45
    tau_sq: float = 0.45
    max_stressed: float = 0.50
    max_bear: float = 0.50
    max_gap: float | None = None
    max_vol20: float | None = None
    stop_atr: float = 2.0
    target_atr: float = 3.0
    max_hold: int = 10


class GatesConfig(BaseModel):
    min_sharpe: float = 1.5
    max_drawdown: float = 0.15
    min_hit_rate: float = 0.55
    min_tstat: float = 2.0
    min_test_years: float = 2.0
    min_regimes: int = 2
    min_regime_share: float = 0.10
    min_trades: int = 100


class CalibrationGateConfig(BaseModel):
    max_ece: float = 0.06
    min_samples: int = 500
    window_days: int = 250


class ResearchConfig(BaseModel):
    """Threshold grids are multiples ("lift") of each question's training-window base rate, so
    they stay reachable whatever the label's prevalence. Risk filters are absolute."""

    val_frac: float = 0.5
    max_trials: int = 150
    seed: int = 11
    lift_dir: list[float] = [1.0, 1.15, 1.3, 1.5]
    lift_bp: list[float] = [1.0, 1.2, 1.4]
    lift_sq: list[float] = [1.0, 1.1, 1.2]
    max_stressed: list[float] = [0.15, 0.25, 1.0]
    max_bear: list[float] = [0.20, 0.30, 1.0]
    stop_atr: list[float] = [1.5, 2.0, 3.0]
    target_atr: list[float] = [1.5, 2.0, 3.0, 4.0]
    max_hold: list[int] = [5, 10]


class RuntimeConfig(BaseModel):
    initial_equity: float = 1_000_000.0
    db_path: str = "data/octoquant.db"
    artifacts_dir: str = "artifacts"
    reports_dir: str = "reports"
    strategy_md: str = "strategy.md"
    run_after_ist: str = "16:10"
    holidays: list[str] = Field(default_factory=list)
    min_paper_days: int = 20


class SlowBrainConfig(BaseModel):
    model: str = "claude-opus-5-5"
    max_rules_per_night: int = 1
    min_improvement: float = 0.10
    max_test_degradation: float = 0.10


# ---- index options ---------------------------------------------------------------------------
class OptionCostConfig(BaseModel):
    """NSE index-option charges. Rates are ASSUMPTIONS as of late 2026: verify against your broker."""

    brokerage_per_order: float = 20.0      # flat, per leg per fill
    stt_sell_premium_pct: float = 0.001    # on premium, sell side
    stt_exercise_pct: float = 0.00125      # on intrinsic value of exercised (ITM) long legs
    exchange_txn_pct: float = 0.0003503    # on premium
    sebi_pct: float = 0.000001
    stamp_buy_pct: float = 0.00003         # on premium, buy side
    gst_pct: float = 0.18                  # on brokerage + exchange + SEBI
    slippage_pct: float = 0.01             # of premium, against you
    min_slippage: float = 0.10             # rupees per unit (two ticks)


class OptionRiskConfig(BaseModel):
    initial_capital: float = 1_000_000.0
    risk_per_trade_pct: float = 0.02       # rupee loss budget per position (max loss or stop loss)
    max_margin_pct: float = 0.50           # blocked margin cap as a fraction of equity
    naked_margin_pct: float = 0.12         # ASSUMPTION: SPAN+exposure per naked short lot, of notional
    max_lots: int = 20
    max_open_positions: int = 2
    max_drawdown_pct: float = 0.25         # kill switch: flatten and halt


class OptionStrategyParams(BaseModel):
    name: str = "iron_condor"
    width_steps: int = 4                   # short strikes this many strike steps from ATM
    wing_steps: int = 4                    # long hedge this many steps beyond the short strike
    entry_dte: int = 7                     # enter the first trading day with calendar DTE <= this
    min_dte: int = 2                       # never enter with fewer calendar days than this
    exit_dte: int = 0                      # exit at the open once DTE <= this (0 = hold to expiry)
    stop_loss_mult: float = 1.5            # credit trades: exit when loss >= mult x entry credit
    take_profit_pct: float = 0.6           # exit when profit >= this share of max profit
    debit_stop_pct: float = 0.5            # debit trades: exit when loss >= this share of debit
    min_iv_rank: float | None = None       # premium selling only when ATM IV rank (0-1) >= this
    max_iv_rank: float | None = None       # premium buying only when ATM IV rank <= this


class OptionsConfig(BaseModel):
    source: Literal["model", "bhavcopy"] = "model"
    paper_enabled: bool = False            # `serve` also steps the options paper book each day
    underlying: str = "NIFTY"
    chain_dir: str = "data/options"        # bhavcopy CSVs (old F&O or UDiFF format), any number
    underlying_csv: str | None = None      # date, open, high, low, close[, vix]; else data.source index
    lot_size: int = 75                     # ASSUMPTION: NSE revises lot sizes; check the current circular
    strike_step: float = 50.0
    expiry_weekday: int = 1                # model chain only: 0=Mon. ASSUMPTION: NIFTY weekly on Tuesday
    expiry_cycle: Literal["weekly", "monthly"] = "weekly"
    risk_free: float = 0.065
    dividend_yield: float = 0.012
    iv_multiplier: float = 1.0             # model chain without VIX: IV = realised vol x this
    iv_floor: float = 0.08
    skew: float = 0.0                      # model chain: sigma(K) = atm * (1 - skew * ln(K/S))
    compare: list[str] = Field(default_factory=lambda: [
        "iron_condor", "short_strangle", "short_straddle", "iron_butterfly",
        "bull_put_spread", "long_straddle"])
    costs: OptionCostConfig = Field(default_factory=OptionCostConfig)
    risk: OptionRiskConfig = Field(default_factory=OptionRiskConfig)
    strategy: OptionStrategyParams = Field(default_factory=OptionStrategyParams)


class Config(BaseModel):
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    costs: CostConfig = Field(default_factory=CostConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    sizing: SizingConfig = Field(default_factory=SizingConfig)
    strategy: StrategyParams = Field(default_factory=StrategyParams)
    gates: GatesConfig = Field(default_factory=GatesConfig)
    calibration: CalibrationGateConfig = Field(default_factory=CalibrationGateConfig)
    research: ResearchConfig = Field(default_factory=ResearchConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    slow_brain: SlowBrainConfig = Field(default_factory=SlowBrainConfig)
    options: OptionsConfig = Field(default_factory=OptionsConfig)


def load_config(path: str | Path | None = None) -> Config:
    if path is None:
        default = Path("config/default.yaml")
        if not default.exists():
            return Config()
        path = default
    with open(path) as fh:
        raw = yaml.safe_load(fh) or {}
    return Config.model_validate(raw)
