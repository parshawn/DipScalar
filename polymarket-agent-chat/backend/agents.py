"""Agent: interpret user prompt and run Polymarket data/trade actions + Liquid perps."""
import os
import json
import logging
from polymarket import fetch_events, flatten_markets, filter_by_query
from liquid import get_liquid_markets, get_ticker

logger = logging.getLogger("agents")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")



def _liquid_symbols_for_query(query: str, available_symbols: list[str]) -> list[str]:
    """Match query words against available Liquid symbol/ticker names. Strict matching to avoid false positives."""
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
            # Exact match always works
            if word == ticker:
                out.append(sym)
                break
            # Only allow substring matching if BOTH are 4+ chars (avoids "nfl" in "nflx", "sol" in "resolv")
            if len(word) >= 4 and len(ticker) >= 4:
                if word in ticker or ticker in word:
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
                    '"search_terms" (array of 5-15 keywords to find related Polymarket prediction markets. '
                    'CRITICAL: These terms are matched against prediction market QUESTION TITLES like "Will inflation reach 3%?" or "Will the Fed decrease interest rates?". '
                    'Always include SIMPLE single words that appear in market titles (e.g. "inflation", "fed", "recession"), '
                    'PLUS multi-word phrases for specificity (e.g. "rate cut", "interest rate", "crude oil"). '
                    'Mix of both single words and phrases is essential. '
                    'Examples: "hedge against inflation" -> ["inflation", "fed", "rate cut", "interest rate", "recession", "gdp", "tariff", "economic"]. '
                    '"football" -> ["nfl", "football", "nfl draft", "super bowl", "quarterback"]. '
                    '"oil" -> ["oil", "crude", "opec", "brent", "energy"]. '
                    'Do NOT use overly specific academic phrases like "CPI inflation forecast" that would never appear in a market title), '
                    '"liquid_symbols" (array of 0-15 symbols from the EXACT available list above that DIRECTLY relate to the user request; '
                    'include ALL relevant symbols across different providers like xyz:, flx:, km:, cash:, hyna: prefixes. '
                    'IMPORTANT: only include symbols that are DIRECTLY related to the query. If nothing matches, return an empty array. '
                    'Do NOT include random tokens. For example, "football" should NOT return NFLX (Netflix), SUPER-PERP (a crypto token), etc. '
                    'Only return symbols for actual tradeable assets related to the topic).'
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

    logger.info(f"Claude parsed: intent={intent}, search_terms={search_terms}, liquid_symbols={claude_liquid}")

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

        # Group by event_title to avoid showing 30+ outcomes for the same event
        event_groups = {}
        for m in markets:
            et = m.get("event_title") or m.get("question") or "Unknown"
            event_groups.setdefault(et, []).append(m)
        # Sort each group by volume, sort groups by total volume
        grouped_markets = []
        for et, group in sorted(event_groups.items(), key=lambda x: sum(float(m.get("volume") or 0) for m in x[1]), reverse=True):
            sorted_group = sorted(group, key=lambda m: float(m.get("volume") or 0), reverse=True)
            grouped_markets.append({
                "event_title": et,
                "slug": sorted_group[0].get("slug"),
                "market_count": len(sorted_group),
                "total_volume": sum(float(m.get("volume") or 0) for m in sorted_group),
                "top_market": sorted_group[0],  # highest volume market shown by default
                "markets": sorted_group[:20],    # cap at 20 outcomes per event
            })
        # Filter out event groups whose title doesn't relate to any search term
        # This catches false positives like "inflation" showing up in "football" results
        if all_terms:
            core_query = prompt_lower.split()
            core_words = [w for w in core_query if len(w) >= 3 and w not in ("show", "me", "markets", "give", "list", "the", "for", "and")]
            if core_words:
                filtered_groups = []
                for g in grouped_markets:
                    title_lower = g["event_title"].lower()
                    # Keep if event title contains any core query word OR any of the first 3 search terms
                    check_terms = core_words + all_terms[:3]
                    if any(t in title_lower for t in check_terms):
                        filtered_groups.append(g)
                # Only apply filter if it doesn't eliminate everything
                if filtered_groups:
                    grouped_markets = filtered_groups
        grouped_markets = grouped_markets[:20]

        # Claude may pick symbols, otherwise search dynamically against real available symbols
        # Always validate: fuzzy search first, then use Claude picks only if they overlap or fuzzy found nothing
        fuzzy_syms = _liquid_symbols_for_query(" ".join(all_terms), available_symbols)
        if claude_liquid:
            valid_claude = [s for s in claude_liquid if s in available_symbols]
            if fuzzy_syms:
                # Only keep Claude picks that fuzzy search ALSO matched (prevents hallucination)
                fuzzy_set = set(fuzzy_syms)
                syms = fuzzy_syms + [s for s in valid_claude if s in fuzzy_set]
                syms = list(dict.fromkeys(syms))  # dedupe preserving order
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

        # Deduplicate Liquid markets: same underlying asset across providers (e.g. xyz:GOLD, cash:GOLD, km:GOLD)
        # Keep only the highest volume one per underlying ticker
        # Normalize ticker aliases to a canonical name
        _ticker_aliases = {
            "WTI": "OIL", "CL": "OIL", "USOIL": "OIL", "BRENTOIL": "OIL", "USENERGY": "OIL",
            "GOLDJM": "GOLD", "GLDMINE": "GOLD", "PAXG": "GOLD",
            "SILVERJM": "SILVER",
            "USA500": "SP500", "US500": "SP500", "XYZ100": "NASDAQ", "USA100": "NASDAQ", "USTECH": "NASDAQ",
            "SMALL2000": "RUSSELL", "JPN225": "NIKKEI", "JP225": "NIKKEI",
        }
        def _underlying(symbol):
            """Extract the canonical underlying asset name from any symbol format."""
            if ":" in symbol:
                ticker = symbol.split(":")[-1].upper()
            elif symbol.endswith("-PERP"):
                ticker = symbol[:-5].upper()
            else:
                ticker = symbol.upper()
            return _ticker_aliases.get(ticker, ticker)

        seen_underlying = {}
        deduped_liquid = []
        for m in sorted(liquid_list, key=lambda x: float(x.get("volume_24h") or 0), reverse=True):
            u = _underlying(m["symbol"])
            if u not in seen_underlying:
                seen_underlying[u] = True
                deduped_liquid.append(m)
        liquid_list = deduped_liquid

        liquid_list = liquid_list[:25]

        theme_label = (" ".join(all_terms[:3]) or prompt or "").strip()[:80]
        total_markets = sum(g["market_count"] for g in grouped_markets)
        has_poly = len(grouped_markets) > 0
        has_liquid = len(liquid_list) > 0
        if has_poly and has_liquid:
            text = f"Found {total_markets} market(s) across {len(grouped_markets)} event(s) and {len(liquid_list)} Liquid perp(s)."
        elif has_poly:
            text = f"Found {total_markets} market(s) across {len(grouped_markets)} event(s). No matching Liquid perps."
        elif has_liquid:
            text = f"No Polymarket markets found. Found {len(liquid_list)} Liquid perp(s)."
        else:
            text = f"No markets found on either Polymarket or Liquid for \"{theme_label}\". Try a different search term."
        return {
            "text": text,
            "event_groups": grouped_markets if grouped_markets else None,
            "markets": None,  # deprecated, use event_groups
            "liquid_markets": liquid_list if liquid_list else None,
            "theme": theme_label,
        }

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
