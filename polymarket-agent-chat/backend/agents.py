"""Agent: interpret user prompt and run Polymarket data/trade actions + Liquid perps."""
import os
import json
from polymarket import fetch_events, flatten_markets, filter_by_query
from liquid import get_liquid_markets, get_ticker

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

# Theme keywords -> Liquid perp symbols (README: CL-PERP oil, GC-PERP gold, etc.)
THEME_SYMBOLS = {
    "oil": ["CL-PERP", "GC-PERP"],
    "crypto": ["BTC-PERP", "ETH-PERP", "SOL-PERP"],
    "gold": ["GC-PERP"],
    "silver": ["SI-PERP"],
    "iran": ["CL-PERP", "GC-PERP"],
    "btc": ["BTC-PERP"],
    "eth": ["ETH-PERP"],
}

# Expand query to related terms so we get more Polymarket markets (e.g. "iran" -> geopolit, fifa, oil)
QUERY_EXPANSION = {
    "iran": ["iran", "geopolit", "fifa", "world cup", "oil", "israel", "middle east", "escalat"],
    "oil": ["oil", "crude", "opec", "wti", "cl ", "energy", "gas"],
    "trump": ["trump", "elect", "republican", "president"],
    "crypto": ["crypto", "bitcoin", "btc", "eth", "ethereum", "sol"],
}


def _liquid_symbols_for_query(query: str):
    """Return list of Liquid perp symbols matching theme (from THEME_SYMBOLS)."""
    q = (query or "").strip().lower()
    out = set()
    for kw, syms in THEME_SYMBOLS.items():
        if kw in q:
            out.update(syms)
    if out:
        return list(out)
    return ["BTC-PERP", "ETH-PERP", "CL-PERP", "GC-PERP"]


def _short_query_from_prompt(prompt: str) -> str:
    """Derive a short search query when Claude is not used. Picks theme words from prompt."""
    stop = {"show", "me", "list", "get", "find", "search", "markets", "events", "the", "a", "an", "for", "and", "or", "batch", "prediction", "related", "perps", "perp"}
    words = [w for w in (prompt or "").lower().split() if w not in stop and len(w) > 1]
    return " ".join(words[:4]) if words else (prompt or "").strip().lower()[:50]


async def _claude_parse_request(prompt: str, available_liquid_symbols: list[str]) -> dict:
    """
    One-shot: interpret any user message. Returns intent (markets|trade|general),
    search_terms for Polymarket, and optional liquid_symbols to show.
    """
    if not ANTHROPIC_API_KEY:
        return {"intent": "general", "search_terms": [], "liquid_symbols": []}
    try:
        import anthropic
        client = anthropic.AsyncAnthropic()
        symbols_preview = (available_liquid_symbols or [])[:50]
        msg = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=400,
            messages=[{
                "role": "user",
                "content": (
                    f"User said: \"{prompt}\"\n\n"
                    "Available Liquid perp symbols (examples): " + ", ".join(symbols_preview) + "\n\n"
                    "Reply with ONLY valid JSON, no markdown or explanation. Keys: "
                    '"intent" (one of: markets, trade, general), '
                    '"search_terms" (array of 2-8 words/phrases to find related Polymarket prediction markets, e.g. iran, geopolit, oil, election), '
                    '"liquid_symbols" (array of 0-15 symbols from the available list that fit the user request; if empty we show defaults).'
                )
            }]
        )
        raw = (msg.content[0].text if hasattr(msg.content[0], "text") else str(msg.content[0])).strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        data = json.loads(raw)
        return {
            "intent": (data.get("intent") or "general").lower()[:20],
            "search_terms": [str(t).strip() for t in (data.get("search_terms") or []) if str(t).strip()][:12],
            "liquid_symbols": [str(s).strip() for s in (data.get("liquid_symbols") or []) if str(s).strip()][:20],
        }
    except Exception:
        return {"intent": "general", "search_terms": [], "liquid_symbols": []}


async def _claude_select_batch(prompt: str, markets: list[dict], liquid: list[dict]) -> tuple[set[str], set[str]]:
    """
    Ask Claude to pick a small batch of Polymarket markets + Liquid symbols.
    Returns (polymarket_ids, liquid_symbols) sets. Falls back to empty sets on error.
    """
    if not ANTHROPIC_API_KEY or not markets:
        return set(), set()
    try:
        import anthropic

        client = anthropic.AsyncAnthropic()
        # Keep payload small: top 40 Polymarket by volume, top 10 Liquid by volume_24h
        pm_sorted = sorted(
            markets,
            key=lambda m: float(m.get("volume") or 0),
            reverse=True,
        )[:40]
        liq_sorted = sorted(
            liquid or [],
            key=lambda m: float(m.get("volume_24h") or 0),
            reverse=True,
        )[:10]
        pm_lines = [
            {
                "id": m.get("market_id"),
                "title": m.get("event_title"),
                "question": m.get("question"),
                "yes_price": m.get("yes_price"),
                "volume": m.get("volume"),
            }
            for m in pm_sorted
        ]
        liq_lines = [
            {
                "symbol": m.get("symbol"),
                "mark_price": m.get("mark_price"),
                "volume_24h": m.get("volume_24h"),
            }
            for m in liq_sorted
        ]
        system_msg = (
            "You are a trading batch builder. Given Polymarket prediction markets and Liquid perpetuals, "
            "you choose a small, thematically coherent batch for the user's query. "
            "Respond with STRICT JSON, no explanations."
        )
        user_msg = {
            "role": "user",
            "content": json.dumps(
                {
                    "query": prompt,
                    "polymarket": pm_lines,
                    "liquid": liq_lines,
                    "format": {
                        "type": "object",
                        "properties": {
                            "polymarket_ids": {"type": "array", "items": {"type": "string"}},
                            "liquid_symbols": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                }
            ),
        }
        msg = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=600,
            messages=[
                {"role": "system", "content": system_msg},
                user_msg,
            ],
        )
        block = msg.content[0]
        raw = block.text if hasattr(block, "text") else str(block)
        data = json.loads(raw)
        pm_ids = {str(x) for x in data.get("polymarket_ids") or []}
        liq_syms = {str(x) for x in data.get("liquid_symbols") or []}
        return pm_ids, liq_syms
    except Exception:
        return set(), set()


async def run_agent(prompt: str) -> dict:
    """
    Returns { "text": str, "markets": list | None, "liquid_markets": list | None }.
    Uses Claude to interpret any question and drive Polymarket + Liquid fetch/execute.
    """
    prompt_lower = (prompt or "").strip().lower()
    # Get Liquid symbol list once for Claude and for building liquid_list
    all_liq_raw: list = []
    try:
        all_liq_raw = await get_liquid_markets() or []
    except Exception:
        pass
    available_symbols = []
    for m in all_liq_raw:
        s = (m.get("symbol") if isinstance(m, dict) else getattr(m, "symbol", None)) or ""
        if s:
            available_symbols.append(s)

    parsed = await _claude_parse_request(prompt, available_symbols)
    intent = parsed.get("intent") or "general"
    search_terms = parsed.get("search_terms") or []
    claude_liquid = [s for s in (parsed.get("liquid_symbols") or []) if s]

    wants_data = intent in ("markets", "trade") or any(
        x in prompt_lower
        for x in (
            "show", "list", "get", "find", "search", "markets", "events",
            "what", "which", "oil", "crypto", "iran", "btc", "trump", "price",
            "gold", "silver", "perps", "batch", "prediction", "bets", "bet"
        )
    )

    if wants_data:
        # Build Polymarket filter: use Claude search_terms when present, else legacy query
        if search_terms:
            query = search_terms[0]
            extra = search_terms[1:] if len(search_terms) > 1 else None
        else:
            query = _short_query_from_prompt(prompt)
            extra = []
            for key, terms in QUERY_EXPANSION.items():
                if key in (query or "").lower():
                    extra = terms[1:]
                    break
            extra = extra if extra else None

        events = await fetch_events(limit=200)
        all_markets = flatten_markets(events)
        markets = filter_by_query(all_markets, query, extra_terms=extra)
        if not markets and (search_terms or query):
            for term in (search_terms or [query]):
                if not term or len(term) < 2:
                    continue
                markets = filter_by_query(all_markets, term)
                if markets:
                    break
        if not markets:
            markets = sorted(
                all_markets,
                key=lambda m: float(m.get("volume") or 0),
                reverse=True,
            )[:30]
            query = ""
        else:
            markets = markets[:60]

        syms = claude_liquid if claude_liquid else _liquid_symbols_for_query(query or " ".join(search_terms))
        liquid_list: list[dict] = []
        try:
            for m in (all_liq_raw or []):
                s = (m.get("symbol") if isinstance(m, dict) else getattr(m, "symbol", None)) or ""
                if s in syms:
                    tick = await get_ticker(s)
                    liquid_list.append({
                        "symbol": s,
                        "max_leverage": m.get("max_leverage") if isinstance(m, dict) else getattr(m, "max_leverage", None),
                        "mark_price": tick.get("mark_price") if tick else None,
                        "volume_24h": tick.get("volume_24h") if tick else None,
                    })
        except Exception:
            pass
        if not liquid_list and syms:
            for s in syms:
                liquid_list.append({"symbol": s, "max_leverage": None, "mark_price": None, "volume_24h": None})

        # Optionally use Claude to reorder or highlight; keep ALL theme-matched markets on both platforms
        pm_ids, liq_syms = await _claude_select_batch(prompt, markets, liquid_list)
        if pm_ids and len(pm_ids) >= 5:
            filtered = [m for m in markets if str(m.get("market_id")) in pm_ids]
            if filtered:
                markets = filtered
        # Show all Liquid perps for theme (no cap by Claude unless we have many)
        if liq_syms and len(liq_syms) >= 3:
            liquid_list = [m for m in liquid_list if m.get("symbol") in liq_syms]
        # Cap display at sensible limits but show many
        markets = markets[:40]
        liquid_list = liquid_list[:25]

        if markets:
            text = f"Found {len(markets)} Polymarket markets." if query else f"No theme-specific match; showing top {len(markets)} markets by volume."
        else:
            text = "No matching Polymarket markets for that theme."
        if liquid_list:
            text += f" {len(liquid_list)} Liquid perp(s) — set size and click Execute to place orders."
        theme_label = (query or " ".join(search_terms) or prompt or "").strip()[:80]
        return {"text": text, "markets": markets if markets else None, "liquid_markets": liquid_list if liquid_list else None, "theme": theme_label}

    if any(x in prompt_lower for x in ("buy", "sell", "order", "trade", "place", "execute")):
        return {
            "text": "Ask for a theme (e.g. 'Oil markets' or 'Crypto perps') to see a batch; then use the Execute button to place Liquid orders.",
            "markets": None,
            "liquid_markets": None,
            "theme": None,
        }
    return {
        "text": "You can ask for market data (e.g. 'Show me oil markets') or 'List crypto perps'. Liquid orders can be executed from the batch card.",
        "markets": None,
        "liquid_markets": None,
        "theme": None,
    }
