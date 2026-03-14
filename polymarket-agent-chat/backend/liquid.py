"""Liquid API client — market data + order execution. Requires LIQUID_API_KEY and LIQUID_API_SECRET."""
import os
import asyncio
import logging

logger = logging.getLogger("liquid")
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

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
        logger.debug(f"get_liquid_markets() raw type: {type(markets)}")
        if markets and isinstance(markets, list):
            # Log first 5 items fully to understand the structure
            for i, m in enumerate(markets[:5]):
                if isinstance(m, dict):
                    logger.debug(f"  market[{i}] (dict): {m}")
                else:
                    logger.debug(f"  market[{i}] (obj type={type(m).__name__}): {vars(m) if hasattr(m, '__dict__') else dir(m)}")
            logger.info(f"Total markets returned: {len(markets)}")
        else:
            logger.warning(f"get_liquid_markets() returned non-list or empty: {markets}")
            return []
        out = []
        for m in markets:
            # SDK may return dicts or objects — handle both
            if isinstance(m, dict):
                sym = m.get("symbol", "")
                lev = m.get("max_leverage")
                # Log all keys so we can see the full structure
            else:
                sym = getattr(m, "symbol", "")
                lev = getattr(m, "max_leverage", None)
            if sym:
                out.append({"symbol": sym, "max_leverage": lev})
        # Log all symbol names
        all_syms = [x["symbol"] for x in out]
        logger.info(f"All {len(all_syms)} Liquid symbols: {all_syms}")
        return out
    return await asyncio.to_thread(_get)


async def get_ticker(symbol: str):
    """Return dict with mark_price, volume_24h, funding_rate or None."""
    c = _client()
    if not c:
        return None
    def _get():
        logger.debug(f"get_ticker({symbol}) calling API...")
        t = c.get_ticker(symbol)
        logger.debug(f"get_ticker({symbol}) raw result type={type(t)}: {vars(t) if hasattr(t, '__dict__') else t}")
        if t is None:
            logger.warning(f"get_ticker({symbol}) returned None")
            return None
        # SDK returns string values for prices/volumes; cast to float for frontend
        def _float(v):
            try:
                return float(v) if v is not None else None
            except (ValueError, TypeError):
                return None
        return {
            "mark_price": _float(getattr(t, "mark_price", None)),
            "volume_24h": _float(getattr(t, "volume_24h", None)),
            "funding_rate": _float(getattr(t, "funding_rate", None)),
        }
    return await asyncio.to_thread(_get)


async def place_order(symbol: str, side: str, size: float, leverage: int = 1, order_type: str = "market"):
    """Place order on Liquid. size in USD notional. Returns result dict or raises."""
    c = _client()
    if not c:
        raise RuntimeError("Liquid API credentials not set (LIQUID_API_KEY, LIQUID_API_SECRET)")
    def _place():
        return c.place_order(symbol=symbol, side=side, type=order_type, size=size, leverage=leverage)
    result = await asyncio.to_thread(_place)
    return {"order_id": getattr(result, "order_id", None), "status": getattr(result, "status", None)}
