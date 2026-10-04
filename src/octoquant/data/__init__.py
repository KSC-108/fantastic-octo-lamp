from octoquant.config import Config
from octoquant.data.base import DataPanel, DataProvider, expected_last_trading_day, finalize_panel
from octoquant.data.csv_provider import CSVProvider
from octoquant.data.nse import NSEProvider
from octoquant.data.synthetic import generate_synthetic

__all__ = [
    "CSVProvider", "DataPanel", "DataProvider", "NSEProvider", "expected_last_trading_day",
    "finalize_panel", "generate_synthetic", "load_panel",
]


def load_panel(cfg: Config) -> DataPanel:
    """Load market data from the configured source."""
    src = cfg.data
    if src.source == "synthetic":
        return generate_synthetic(cfg.universe.symbols[:20], seed=1)
    if src.source == "csv":
        return CSVProvider(src.csv_dir).load(cfg.universe.symbols, src.start, src.end)
    return NSEProvider(src.cache_dir, cfg.universe.index).load(
        cfg.universe.symbols, src.start, src.end
    )
