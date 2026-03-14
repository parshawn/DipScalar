"""Agent: interpret user prompt and run Polymarket data/trade actions + Liquid perps."""
import os
import json
import logging
from polymarket import fetch_events, flatten_markets, filter_by_query
from liquid import get_liquid_markets, get_ticker

logger = logging.getLogger("agents")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")



def _liquid_symbols_for_query(query: str, available_symbols: list[str]) -> list[str]:
    """Pure fuzzy search: match query words against available Liquid symbol/ticker names. No hardcoded maps."""
    q = (query or "").strip().lower()
    search_words = [w for w in q.split() if len(w) >= 2]
    if not search_words:
        return []
    out = []
    for sym in available_symbols:
        sym_lower = sym.lower()
        # Extract the ticker part (after : or before -PERP)
        ticker = sym_lower.split(":")[-1].replace("-perp", "")
        if len(ticker) < 2:
            continue
        for word in search_words:
            if word == ticker or (len(word) >= 3 and word in ticker) or (len(ticker) >= 3 and ticker in word):
                out.append(sym)
                break
    logger.info(f"_liquid_symbols_for_query({q!r}) words={search_words} -> matched {len(out)}: {out}")
    return out


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
        symbols_preview = available_liquid_symbols or []
        msg = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            messages=[{
                "role": "user",
                "content": (
                    f"User said: \"{prompt}\"\n\n"
                    "Available Liquid symbols (crypto perps like BTC-PERP, commodities like xyz:CL or flx:OIL, "
                    "stocks like xyz:NVDA, indices like abcd:USA500): " + ", ".join(symbols_preview) + "\n\n"
                    "Reply with ONLY valid JSON, no markdown or explanation. Keys: "
                    '"intent" (one of: markets, trade, general), '
                    '"search_terms" (array of 5-15 individual keywords/phrases to find related Polymarket prediction markets. '
                    'Be EXHAUSTIVE — include the main term AND all synonyms, related concepts, sub-topics, and key entities. '
                    'For example: "economy" -> ["fed", "rate", "recession", "inflation", "gdp", "tariff", "treasury", "unemployment", "economic", "jobs", "cpi"]. '
                    '"sports" -> ["nba", "nfl", "mlb", "nhl", "soccer", "football", "basketball", "baseball", "champion", "finals", "premier league", "world cup"]. '
                    'Think about what words would appear in prediction market QUESTIONS about this topic), '
                    '"liquid_symbols" (array of 0-15 symbols from the EXACT available list above that DIRECTLY relate to the user request; '
                    'include ALL relevant symbols across different providers like xyz:, flx:, km:, cash:, hyna: prefixes. '
                    'IMPORTANT: only include symbols that are genuinely related to the query. If nothing matches, return an empty array. '
                    'Do NOT include random or loosely related symbols just to fill the list).'
                )
            }]
        )
        raw = (msg.content[0].text if hasattr(msg.content[0], "text") else str(msg.content[0])).strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        data = json.loads(raw)
        return {
            "intent": (data.get("intent") or "general").lower()[:20],
            "search_terms": [str(t).strip() for t in (data.get("search_terms") or []) if str(t).strip()][:20],
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
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=system_msg,
            messages=[user_msg],
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
        # Build Polymarket filter: use ALL search terms as OR query
        if search_terms:
            all_terms = [t.lower().strip() for t in search_terms if t.strip()]
        else:
            q = _short_query_from_prompt(prompt)
            all_terms = [q] if q else []

        events = await fetch_events(limit=500)
        all_markets = flatten_markets(events)
        # Search with all terms at once (OR logic)
        markets = filter_by_query(all_markets, all_terms[0] if all_terms else "", extra_terms=all_terms[1:] if len(all_terms) > 1 else None)
        # Sort by volume so best markets come first
        markets = sorted(markets, key=lambda m: float(m.get("volume") or 0), reverse=True)[:60]

        # Claude may pick symbols, otherwise search dynamically against real available symbols
        # Always validate: fuzzy search first, then use Claude picks only if they overlap or fuzzy found nothing
        fuzzy_syms = _liquid_symbols_for_query(" ".join(all_terms), available_symbols)
        if claude_liquid:
            valid_claude = [s for s in claude_liquid if s in available_symbols]
            # If fuzzy search found results, only keep Claude picks that fuzzy also found (prevents hallucination)
            # If fuzzy found nothing, trust Claude's picks
            if fuzzy_syms:
                syms = list(set(fuzzy_syms + valid_claude))
            else:
                syms = valid_claude
            logger.info(f"Claude picked: {claude_liquid} -> valid: {valid_claude}, fuzzy: {fuzzy_syms}, final: {syms}")
        else:
            syms = fuzzy_syms
        logger.info(f"Final Liquid symbols to fetch tickers for: {syms}")
        liquid_list: list[dict] = []
        for m in (all_liq_raw or []):
            s = (m.get("symbol") if isinstance(m, dict) else getattr(m, "symbol", None)) or ""
            if s in syms:
                try:
                    tick = await get_ticker(s)
                    logger.info(f"Ticker for {s}: {tick}")
                    if tick and tick.get("mark_price") is not None:
                        liquid_list.append({
                            "symbol": s,
                            "max_leverage": m.get("max_leverage") if isinstance(m, dict) else getattr(m, "max_leverage", None),
                            "mark_price": tick.get("mark_price"),
                            "volume_24h": tick.get("volume_24h"),
                        })
                except Exception as e:
                    logger.error(f"Error fetching ticker for {s}: {e}")

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

        theme_label = (" ".join(all_terms[:3]) or prompt or "").strip()[:80]
        has_poly = len(markets) > 0
        has_liquid = len(liquid_list) > 0
        if has_poly and has_liquid:
            text = f"Found {len(markets)} Polymarket market(s) and {len(liquid_list)} Liquid perp(s) for \"{theme_label}\"."
        elif has_poly:
            text = f"Found {len(markets)} Polymarket market(s) for \"{theme_label}\". No matching Liquid perps."
        elif has_liquid:
            text = f"No Polymarket markets found for \"{theme_label}\". Found {len(liquid_list)} Liquid perp(s)."
        else:
            text = f"No markets found on either Polymarket or Liquid for \"{theme_label}\". Try a different search term."
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
