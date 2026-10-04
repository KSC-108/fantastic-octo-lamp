"""Indian delivery-equity transaction costs and slippage. Rates come from CostConfig."""

from __future__ import annotations

from octoquant.config import CostConfig


def trade_costs(side: str, notional: float, c: CostConfig) -> float:
    """Rupee cost of one leg. side is 'buy' or 'sell'."""
    brokerage = c.brokerage_flat + c.brokerage_pct * notional
    txn = c.exchange_txn_pct * notional
    sebi = c.sebi_pct * notional
    stt = c.stt_pct * notional
    stamp = c.stamp_buy_pct * notional if side == "buy" else 0.0
    dp = c.dp_charge_sell if side == "sell" else 0.0
    gst = c.gst_pct * (brokerage + txn + sebi + dp)
    return brokerage + txn + sebi + stt + stamp + dp + gst


def slipped_price(price: float, side: str, c: CostConfig) -> float:
    bps = c.slippage_bps / 10_000.0
    return price * (1 + bps) if side == "buy" else price * (1 - bps)


def round_trip_cost_pct(c: CostConfig, notional: float = 100_000.0) -> float:
    """Approximate round-trip cost as a fraction of notional, including slippage."""
    fees = trade_costs("buy", notional, c) + trade_costs("sell", notional, c)
    return fees / notional + 2 * c.slippage_bps / 10_000.0
