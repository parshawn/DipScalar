import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agents import run_agent
from liquid import place_order as liquid_place_order
from liquid import get_candles as liquid_get_candles
from polymarket_clob import place_order as poly_place_order

app = FastAPI(title="Polymarket Agent Chat")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AgentRequest(BaseModel):
    prompt: str


class LiquidOrder(BaseModel):
    symbol: str
    side: str
    size: float
    leverage: int = 1


class PolymarketOrder(BaseModel):
    token_id: str
    amount_usd: float
    price_limit: float = 0.99


class ExecuteRequest(BaseModel):
    liquid_orders: list[LiquidOrder] = []
    polymarket_orders: list[PolymarketOrder] = []


@app.post("/agent")
async def agent_endpoint(req: AgentRequest):
    result = await run_agent(req.prompt)
    return result


@app.post("/execute")
async def execute_endpoint(req: ExecuteRequest):
    results = []
    for o in req.liquid_orders:
        try:
            r = await liquid_place_order(o.symbol, o.side, o.size, o.leverage)
            results.append({"venue": "liquid", "symbol": o.symbol, "side": o.side, **r})
        except Exception as e:
            results.append({"venue": "liquid", "symbol": o.symbol, "side": o.side, "error": str(e)})
    for o in req.polymarket_orders:
        try:
            r = await poly_place_order(o.token_id, o.amount_usd, o.price_limit)
            results.append({"venue": "polymarket", "token_id": o.token_id[:16] + "...", **r})
        except Exception as e:
            results.append({"venue": "polymarket", "token_id": o.token_id[:16] + "...", "error": str(e)})
    return {"results": results}


@app.post("/batch-charts")
async def batch_charts(req: dict):
    """Fetch chart data for multiple markets/symbols in parallel."""
    import httpx
    import asyncio

    poly_tokens = req.get("poly_tokens") or []   # list of token IDs
    liquid_symbols = req.get("liquid_symbols") or []  # list of symbols
    poly_interval = req.get("poly_interval", "1d")
    liquid_interval = req.get("liquid_interval", "1h")
    liquid_limit = req.get("liquid_limit", 24)

    results = {"poly": {}, "liquid": {}}

    async def fetch_poly(token_id):
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    "https://clob.polymarket.com/prices-history",
                    params={"market": token_id, "interval": poly_interval, "fidelity": 60},
                    timeout=10,
                )
                r.raise_for_status()
                results["poly"][token_id] = r.json().get("history", [])
        except Exception:
            results["poly"][token_id] = []

    async def fetch_liquid(symbol):
        try:
            data = await liquid_get_candles(symbol, interval=liquid_interval, limit=liquid_limit)
            results["liquid"][symbol] = data
        except Exception:
            results["liquid"][symbol] = []

    tasks = [fetch_poly(t) for t in poly_tokens] + [fetch_liquid(s) for s in liquid_symbols]
    await asyncio.gather(*tasks)

    return results


@app.get("/trending-batches")
async def trending_batches():
    """Fetch Polymarket events, group by broad category tags, return top 6 with real counts."""
    import httpx
    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://gamma-api.polymarket.com/events",
            params={"active": "true", "closed": "false", "_limit": 500, "order": "volume", "ascending": "false"},
            timeout=20,
        )
        r.raise_for_status()
        events = r.json()

    # Tags to skip (meta/internal tags)
    skip_tags = {"earn", "parent for derivative", "hide from new", "recurring", "monthly",
                 "hit price", "rewards", "macro election"}
    # Keyword-based category detection — if any keyword appears in a tag label, it maps to that category
    category_keywords = {
        "Politics": ["politic", "election", "primary", "president", "congress", "senate", "democrat", "republican", "governor", "nominee"],
        "Sports": ["sport", "nba", "nfl", "mlb", "nhl", "soccer", "football", "basketball", "baseball",
                    "hockey", "golf", "pga", "epl", "la liga", "champion", "ucl", "fifa", "world cup",
                    "stanley cup", "finals", "masters", "tennis", "cricket", "f1", "formula"],
        "Economy": ["econom", "fed", "rate", "inflation", "gdp", "tariff", "treasury", "recession",
                     "unemployment", "jobs", "cpi", "monetary", "interest rate", "powell", "debt"],
        "Crypto": ["crypto", "bitcoin", "btc", "ethereum", "eth", "solana", "defi", "token", "blockchain"],
        "Geopolitics": ["geopolit", "middle east", "iran", "israel", "china", "russia", "ukraine",
                        "venezuela", "foreign policy", "war", "conflict", "nato", "sanction", "regime"],
        "Culture": ["culture", "movie", "oscar", "award", "music", "tv", "celebrity", "entertainment"],
        "Commodities": ["commodit", "oil", "gold", "silver", "crude", "nymex", "energy", "metal"],
        "Trump": ["trump"],
    }

    def classify_tag(label):
        """Match a tag label to broad categories using keyword search."""
        l = label.lower()
        if any(skip in l for skip in skip_tags):
            return []
        cats = []
        for cat, keywords in category_keywords.items():
            if any(kw in l for kw in keywords):
                cats.append(cat)
        return cats

    tag_groups = {}
    seen_events = {}

    for event in events:
        event_tags = event.get("tags") or []
        vol = float(event.get("volume") or 0)
        slug = event.get("slug", "")

        # Find all broad categories from ALL tags on this event
        matched_categories = set()
        for t in event_tags:
            label = t.get("label") if isinstance(t, dict) else str(t)
            if label:
                matched_categories.update(classify_tag(label))
        # Also check event title for category keywords
        title = (event.get("title") or "").lower()
        for cat, keywords in category_keywords.items():
            if any(kw in title for kw in keywords):
                matched_categories.add(cat)

        for cat in matched_categories:
            if cat not in seen_events:
                seen_events[cat] = set()
            if slug in seen_events[cat]:
                continue  # already counted this event for this category
            seen_events[cat].add(slug)

            if cat not in tag_groups:
                tag_groups[cat] = {
                    "label": cat,
                    "image": event.get("image") or "",
                    "top_event": event.get("title", ""),
                    "slug": slug,
                    "total_volume": vol,
                    "event_count": 1,
                }
            else:
                tag_groups[cat]["total_volume"] += vol
                tag_groups[cat]["event_count"] += 1

    # Sort by total volume, take top 6
    sorted_tags = sorted(tag_groups.values(), key=lambda x: x["total_volume"], reverse=True)[:6]

    return {"batches": sorted_tags}


@app.get("/prices-history")
async def prices_history(market: str, interval: str = "1d"):
    """Proxy Polymarket CLOB /prices-history. market = token_id (clob_token_ids[0])."""
    import httpx
    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://clob.polymarket.com/prices-history",
            params={"market": market, "interval": interval, "fidelity": 60},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()


@app.get("/candles")
async def candles(symbol: str, interval: str = "1h", limit: int = 100):
    """Get OHLCV candles from Liquid SDK."""
    import logging
    logger = logging.getLogger("main")
    try:
        data = await liquid_get_candles(symbol, interval=interval, limit=limit)
        logger.info(f"Candles for {symbol}: got {len(data)} candles")
        return {"candles": data}
    except Exception as e:
        logger.error(f"Candles error for {symbol}: {e}")
        return {"candles": [], "error": str(e)}


@app.get("/batches")
async def get_batches():
    """Return curated batch suggestions with live Liquid ticker data, dynamic symbol resolution."""
    from batches import CURATED_BATCHES
    from agents import _liquid_symbols_for_query
    from liquid import get_liquid_markets, get_ticker

    all_liq_raw = []
    try:
        all_liq_raw = await get_liquid_markets() or []
    except Exception:
        pass
    available_symbols = [m.get("symbol", "") for m in all_liq_raw if m.get("symbol")]
    liq_by_symbol = {m.get("symbol"): m for m in all_liq_raw}

    result = []
    for batch in CURATED_BATCHES:
        # Dynamic symbol resolution using search terms against real available symbols
        search_query = " ".join(batch.get("liquid_search_terms", []))
        matched_symbols = _liquid_symbols_for_query(search_query, available_symbols)[:8]

        liquid_markets = []
        for sym in matched_symbols:
            try:
                tick = await get_ticker(sym)
                if tick and tick.get("mark_price") is not None:
                    liquid_markets.append({
                        "symbol": sym,
                        "max_leverage": liq_by_symbol.get(sym, {}).get("max_leverage"),
                        "mark_price": tick.get("mark_price"),
                        "volume_24h": tick.get("volume_24h"),
                    })
            except Exception:
                pass

        result.append({
            "id": batch["id"],
            "title": batch["title"],
            "subtitle": batch["subtitle"],
            "icon": batch["icon"],
            "thesis": batch["thesis"],
            "polymarket_queries": batch["polymarket_queries"],
            "liquid_markets": liquid_markets,
            "liquid_count": len(liquid_markets),
        })
    return {"batches": result}
