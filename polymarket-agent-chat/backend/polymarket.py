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
    """Keyword filter with word-boundary matching to avoid false positives like 'nfl' in 'inflation'."""
    import re
    q = (query or "").strip().lower()
    terms = [q] if q else []
    if extra_terms:
        terms = list(terms) + [t.lower() for t in extra_terms]
    if not terms:
        return markets
    # Build regex patterns: word-boundary for short terms, prefix-match for longer ones
    patterns = []
    for term in terms:
        if not term:
            continue
        escaped = re.escape(term)
        # For terms 4+ chars, allow prefix matching (e.g. "rate" matches "rates", "fed" matches "federal")
        if len(term) >= 4:
            patterns.append(re.compile(r'\b' + escaped, re.IGNORECASE))
        else:
            # Short terms (nfl, oil, fed, etc.) need strict word boundaries to avoid false positives
            patterns.append(re.compile(r'\b' + escaped + r'\b', re.IGNORECASE))
    if not patterns:
        return markets
    def matches(m):
        t = ((m.get("event_title") or "") + " " + (m.get("question") or ""))
        return any(p.search(t) for p in patterns)
    return [m for m in markets if matches(m)]
