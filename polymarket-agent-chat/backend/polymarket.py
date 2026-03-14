"""Polymarket Gamma API client — market data only (no auth)."""
import json
from typing import List, Optional

import httpx

GAMMA_URL = "https://gamma-api.polymarket.com"


async def fetch_events(active: bool = True, closed: bool = False, limit: int = 200) -> list[dict]:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{GAMMA_URL}/events",
            params={"active": str(active).lower(), "closed": str(closed).lower(), "limit": limit},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()


def flatten_markets(events: list[dict]) -> list[dict]:
    """Turn events into a flat list of tradeable markets with event title and slug for URLs."""
    out = []
    for ev in events:
        title = ev.get("title", "")
        slug = ev.get("slug")  # event slug for polymarket.com/event/{slug}
        for m in ev.get("markets", []) or []:
            if m.get("closed") or not m.get("acceptingOrders", True):
                continue
            try:
                prices = json.loads(m.get("outcomePrices") or "[]")
                outcomes = json.loads(m.get("outcomes") or "[]")
            except (json.JSONDecodeError, TypeError):
                prices = []
                outcomes = []
            yes_price = float(prices[0]) if len(prices) > 0 else None
            # market can have its own slug for /market/{slug} fallback
            market_slug = m.get("slug")
            out.append({
                "event_title": title,
                "question": m.get("question", ""),
                "market_id": m.get("id"),
                "condition_id": m.get("conditionId"),
                "slug": slug or market_slug,
                "yes_price": yes_price,
                "outcomes": outcomes,
                "volume": m.get("volumeNum") or m.get("volume"),
                "liquidity": m.get("liquidityNum") or m.get("liquidity"),
                "clob_token_ids": m.get("clobTokenIds"),
            })
    return out


def filter_by_query(markets: List[dict], query: str, extra_terms: Optional[List[str]] = None) -> List[dict]:
    """Keyword filter; match query or any of extra_terms against title + question."""
    q = (query or "").strip().lower()
    terms = [q] if q else []
    if extra_terms:
        terms = list(terms) + [t.lower() for t in extra_terms]
    if not terms:
        return markets
    def matches(m):
        t = ((m.get("event_title") or "") + " " + (m.get("question") or "")).lower()
        return any(term in t for term in terms)
    return [m for m in markets if matches(m)]
