"""Liquid API client — market data + order execution. Requires LIQUID_API_KEY and LIQUID_API_SECRET."""
import os
import asyncio
import logging

logger = logging.getLogger("liquid")
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

def _client():
    key = os.environ.get("LIQUID_API_KEY")
    secret = os.environ.get("LIQUID_API_SECRET")
    if not key or not secret:
        logger.warning(f"Liquid client: missing credentials (key={'set' if key else 'MISSING'}, secret={'set' if secret else 'MISSING'})")
        return None
    from liquidtrading import LiquidClient
    return LiquidClient(api_key=key, api_secret=secret)


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


async def get_candles(symbol: str, interval: str = "1h", limit: int = 100):
    """Return list of OHLCV candle dicts or empty list."""
    c = _client()
    if not c:
        return []
    def _get():
        logger.debug(f"get_candles({symbol}, {interval}, {limit}) calling SDK...")
        try:
            result = c.get_candles(symbol, interval=interval, limit=limit)
        except Exception as e:
            logger.error(f"get_candles({symbol}) SDK error: {e}")
            return []
        logger.debug(f"get_candles({symbol}) raw: type={type(result)}, len={len(result) if result else 0}")
        if result and len(result) > 0:
            item = result[0]
            logger.debug(f"get_candles first item: type={type(item).__name__}, {vars(item) if hasattr(item, '__dict__') else item}")
        if not result:
            return []
        out = []
        for candle in result:
            if isinstance(candle, dict):
                ts = candle.get("timestamp", 0) or 0
                # Convert ms to seconds if needed
                if ts > 1e12:
                    ts = ts / 1000
                out.append({**candle, "timestamp": int(ts)})
            else:
                ts = float(getattr(candle, "timestamp", 0) or 0)
                if ts > 1e12:
                    ts = ts / 1000
                out.append({
                    "t": int(ts),
                    "o": float(getattr(candle, "open", 0) or 0),
                    "h": float(getattr(candle, "high", 0) or 0),
                    "l": float(getattr(candle, "low", 0) or 0),
                    "c": float(getattr(candle, "close", 0) or 0),
                    "v": float(getattr(candle, "volume", 0) or 0),
                })
        return out
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
