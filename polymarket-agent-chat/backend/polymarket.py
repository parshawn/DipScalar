"""Polymarket Gamma API client — market data only (no auth)."""
import json
import logging
from typing import List, Optional

import httpx

GAMMA_URL = "https://gamma-api.polymarket.com"
logger = logging.getLogger("polymarket")


async def search_events(query: str, limit: int = 50) -> list[dict]:
    """Use Gamma /public-search for server-side text search. Returns matching active events."""
    async with httpx.AsyncClient() as client:
        all_events = []
        page = 1
        while len(all_events) < limit:
            r = await client.get(
                f"{GAMMA_URL}/public-search",
                params={
                    "q": query,
                    "events_status": "active",
                    "limit_per_type": min(limit, 50),
                    "page": page,
                },
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()
            events = data.get("events", [])
            if not events:
                break
            all_events.extend(events)
            pagination = data.get("pagination", {})
            if not pagination.get("hasMore", False):
                break
            page += 1
        logger.info(f"search_events({query!r}): {len(all_events)} events")
        return all_events[:limit]


async def fetch_events_by_tag(tag_slug: str, limit: int = 100) -> list[dict]:
    """Fetch events filtered by tag slug (e.g. 'venezuela', 'crypto')."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{GAMMA_URL}/events",
            params={
                "tag_slug": tag_slug,
                "active": "true",
                "closed": "false",
                "limit": limit,
                "order": "volume",
                "ascending": "false",
            },
            timeout=30,
        )
        r.raise_for_status()
        return r.json()


async def fetch_events(active: bool = True, closed: bool = False, limit: int = 500) -> list[dict]:
    """Fetch top events by volume (for trending/general browsing, not search)."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{GAMMA_URL}/events",
            params={
                "active": str(active).lower(),
                "closed": str(closed).lower(),
                "limit": limit,
                "order": "volume",
                "ascending": "false",
            },
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
    # Build regex patterns with word boundaries
    patterns = []
    for term in terms:
        if not term:
            continue
        escaped = re.escape(term)
        if len(term) >= 4:
            # 4+ chars: prefix-match so "rate" matches "rates", "inflation" matches "inflationary"
            patterns.append(re.compile(r'\b' + escaped, re.IGNORECASE))
        else:
            # Short terms: strict word boundaries to avoid "nfl" in "inflation"
            patterns.append(re.compile(r'\b' + escaped + r'\b', re.IGNORECASE))
    if not patterns:
        return markets
    def matches(m):
        t = ((m.get("event_title") or "") + " " + (m.get("question") or ""))
        return any(p.search(t) for p in patterns)
    return [m for m in markets if matches(m)]
