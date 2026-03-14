"""Liquid API client — market data + order execution. Requires LIQUID_API_KEY and LIQUID_API_SECRET."""
import os
import asyncio

LIQUID_API_KEY = os.environ.get("LIQUID_API_KEY")
LIQUID_API_SECRET = os.environ.get("LIQUID_API_SECRET")


def _client():
    if not LIQUID_API_KEY or not LIQUID_API_SECRET:
        return None
    from liquidtrading import LiquidClient
    return LiquidClient(api_key=LIQUID_API_KEY, api_secret=LIQUID_API_SECRET)


async def get_liquid_markets():
    """Return list of dicts: symbol, max_leverage; empty if no credentials."""
    c = _client()
    if not c:
        return []
    def _get():
        markets = c.get_markets()
        return [{"symbol": m.get("symbol", ""), "max_leverage": m.get("max_leverage")} for m in markets] if isinstance(markets, list) else []
    return await asyncio.to_thread(_get)


async def get_ticker(symbol: str):
    """Return dict with mark_price, volume_24h, funding_rate or None."""
    c = _client()
    if not c:
        return None
    def _get():
        t = c.get_ticker(symbol)
        if t is None:
            return None
        return {"mark_price": getattr(t, "mark_price", None), "volume_24h": getattr(t, "volume_24h", None), "funding_rate": getattr(t, "funding_rate", None)}
    return await asyncio.to_thread(_get, symbol)


async def place_order(symbol: str, side: str, size: float, leverage: int = 1, order_type: str = "market"):
    """Place order on Liquid. size in USD notional. Returns result dict or raises."""
    c = _client()
    if not c:
        raise RuntimeError("Liquid API credentials not set (LIQUID_API_KEY, LIQUID_API_SECRET)")
    def _place():
        return c.place_order(symbol=symbol, side=side, type=order_type, size=size, leverage=leverage)
    result = await asyncio.to_thread(_place)
    return {"order_id": getattr(result, "order_id", None), "status": getattr(result, "status", None)}
