"""Polymarket CLOB client — place orders using API creds + private key. Env: POLY_API_KEY, POLY_API_SECRET, POLY_API_PASSPHRASE, POLY_PRIVATE_KEY (required for signing)."""
import os
import asyncio

HOST = "https://clob.polymarket.com"
CHAIN_ID = 137

POLY_API_KEY = os.environ.get("POLY_API_KEY")
POLY_API_SECRET = os.environ.get("POLY_API_SECRET")
POLY_API_PASSPHRASE = os.environ.get("POLY_API_PASSPHRASE")
POLY_PRIVATE_KEY = os.environ.get("POLY_PRIVATE_KEY")


def _client():
    if not all([POLY_API_KEY, POLY_API_SECRET, POLY_API_PASSPHRASE]):
        return None
    if not POLY_PRIVATE_KEY:
        return None
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds
    client = ClobClient(HOST, key=POLY_PRIVATE_KEY, chain_id=CHAIN_ID)
    client.set_api_creds(ApiCreds(
        api_key=POLY_API_KEY,
        api_secret=POLY_API_SECRET,
        api_passphrase=POLY_API_PASSPHRASE,
    ))
    return client


def _can_trade():
    return _client() is not None


async def place_order(token_id: str, amount_usd: float, price_limit: float = 0.99):
    """Place a market order (FOK). amount_usd=spend in USD, price_limit=worst acceptable price 0-1 (slippage)."""
    c = _client()
    if not c:
        raise RuntimeError("Polymarket CLOB credentials not set (POLY_API_KEY, POLY_API_SECRET, POLY_API_PASSPHRASE, POLY_PRIVATE_KEY)")
    from py_clob_client.clob_types import MarketOrderArgs, OrderType
    from py_clob_client.order_builder.constants import BUY
    options = {"tick_size": "0.01", "neg_risk": False}

    def _place():
        mo = MarketOrderArgs(
            token_id=token_id,
            amount=amount_usd,
            side=BUY,
            price=price_limit,
            order_type=OrderType.FOK,
        )
        signed = c.create_market_order(mo, options=options)
        return c.post_order(signed, OrderType.FOK)

    resp = await asyncio.to_thread(_place)
    return {"order_id": resp.get("orderID"), "status": resp.get("status"), "error": resp.get("errorMsg")}
