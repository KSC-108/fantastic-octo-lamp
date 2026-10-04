import numpy as np
import pandas as pd
import pytest

from octoquant.config import CostConfig, ModelConfig
from octoquant.costs import round_trip_cost_pct, slipped_price, trade_costs
from octoquant.data.base import DataPanel, expected_last_trading_day, validate_panel
from octoquant.data.nse import normalise_nse_index_frame, normalise_nse_stock_frame
from octoquant.features import FEATURE_COLUMNS, build_features, build_labels, build_regime_labels


def test_synthetic_panel_is_valid(small_panel):
    validate_panel(small_panel.stocks, small_panel.index)
    assert small_panel.source == "synthetic"
    assert len(small_panel.symbols) == 8


def test_validate_rejects_bad_bounds(small_panel):
    bad = small_panel.stocks.copy()
    bad.loc[0, "high"] = bad.loc[0, "low"] * 0.5
    with pytest.raises(ValueError):
        validate_panel(bad, small_panel.index)


def test_features_have_no_lookahead(small_panel):
    full, _ = build_features(small_panel)
    cut = small_panel.dates[600]
    part, _ = build_features(small_panel.truncate(cut))
    a = full[full["date"] <= cut].reset_index(drop=True)
    b = part.reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b, check_exact=False, rtol=1e-9, atol=1e-12)


def test_feature_columns_present_and_mostly_finite(small_panel):
    feats, _ = build_features(small_panel)
    assert set(FEATURE_COLUMNS) <= set(feats.columns)
    late = feats[feats["date"] > small_panel.dates[300]]
    assert late[FEATURE_COLUMNS].isna().mean().max() < 0.01


def test_labels_are_forward_and_nan_at_tail(small_panel):
    feats, _ = build_features(small_panel)
    lab = build_labels(small_panel, feats, ModelConfig(), CostConfig())
    tail = lab[lab["date"] >= small_panel.dates[-3]]
    assert tail["y_dir"].isna().all()
    assert set(lab["y_dir"].dropna().unique()) <= {0.0, 1.0, 2.0}
    reg = build_regime_labels(small_panel.index, ModelConfig())
    assert reg.iloc[-5:].isna().all()
    assert set(reg.dropna().unique()) <= {0.0, 1.0, 2.0}


def test_costs_are_positive_and_asymmetric():
    c = CostConfig()
    buy, sell = trade_costs("buy", 100_000, c), trade_costs("sell", 100_000, c)
    assert buy > 0 and sell > 0 and sell != buy
    assert slipped_price(100, "buy", c) > 100 > slipped_price(100, "sell", c)
    assert 0.001 < round_trip_cost_pct(c) < 0.01


def test_expected_last_trading_day_skips_weekend_and_holidays():
    import datetime as dt

    assert expected_last_trading_day(dt.date(2026, 10, 4)) == dt.date(2026, 10, 2)
    assert expected_last_trading_day(dt.date(2026, 10, 2), {dt.date(2026, 10, 2)}) == dt.date(
        2026, 10, 1
    )


def test_nse_frame_normalisation_matches_library_headers():
    raw = pd.DataFrame(
        {
            "DATE": ["2024-01-02", "2024-01-03"], "SERIES": ["EQ", "EQ"],
            "OPEN": [100.0, 101.0], "HIGH": [103.0, 104.0], "LOW": [99.0, 100.0],
            "PREV. CLOSE": [100.0, 102.0], "LTP": [102.0, 103.0], "CLOSE": [102.0, 103.5],
            "VWAP": [101.5, 102.5], "VOLUME": [1000, 1200], "VALUE": [1e5, 1.2e5],
            "NO OF TRADES": [10, 12], "DELIVERY QTY": [400, 500], "DELIVERY %": [40.0, 41.7],
            "SYMBOL": ["TCS", "TCS"],
        }
    )
    out = normalise_nse_stock_frame(raw)
    assert list(out.columns) == [
        "date", "symbol", "open", "high", "low", "close", "volume", "vwap", "delivery_pct"
    ]
    assert out["delivery_pct"].iloc[1] == pytest.approx(41.7)
    idx = pd.DataFrame(
        {"HistoricalDate": ["2024-01-02"], "OPEN": ["21000"], "HIGH": ["21100"],
         "LOW": ["20900"], "CLOSE": ["21050"], "INDEX_NAME": ["NIFTY 50"]}
    )
    assert normalise_nse_index_frame(idx)["close"].iloc[0] == 21050.0


def test_truncate_is_point_in_time(small_panel):
    cut = small_panel.dates[100]
    t = small_panel.truncate(cut)
    assert isinstance(t, DataPanel) and t.stocks["date"].max() == cut
    assert np.isfinite(t.index["close"]).all()
