"""Index options: pricing, chain data, strategy templates, backtest and paper trading.

Backtest and paper trading share one simulator step (`OptionsSimulator.step`), as the equity side does.
"""

from octoquant.options.chain import BhavcopyChain, ModelChain, OptionChain, load_bhavcopy
from octoquant.options.engine import OptionsBacktestResult, OptionsSimulator, run_options_backtest
from octoquant.options.pricing import bs_greeks, bs_price, implied_vol
from octoquant.options.strategies import STRATEGIES, StrategySpec

__all__ = [
    "BhavcopyChain", "ModelChain", "OptionChain", "load_bhavcopy", "OptionsBacktestResult",
    "OptionsSimulator", "run_options_backtest", "bs_greeks", "bs_price", "implied_vol",
    "STRATEGIES", "StrategySpec",
]
