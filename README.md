# AI Batch Trading Terminal

## One-liner

An AI-powered terminal where users type a theme (e.g. "Oil", "Iran", "Crypto") and get a cross-platform batch of **Polymarket** prediction markets and **Liquid** perpetual futures, with one-click execution on both.

---

## Workflow: 0 → 100 (code path)

End-to-end flow from user input to executed orders.

### 1. User input (frontend)

- **File:** `polymarket-agent-chat/frontend/src/App.jsx`
- User types in the input bar or clicks a quick theme (Oil, Crypto, Iran, Trump, Gold) or an example prompt.
- `send(prompt)` is called: it appends a user message, sets `loading`, and `POST`s to the backend.

```text
POST /agent  body: { prompt: "Show me oil markets" }
```

---

### 2. Backend receives prompt

- **File:** `polymarket-agent-chat/backend/main.py`
- `agent_endpoint(req: AgentRequest)` receives the prompt and calls `run_agent(req.prompt)`.

---

### 3. Agent: Liquid symbol list

- **File:** `polymarket-agent-chat/backend/agents.py` → `run_agent()`
- First, the agent loads the list of Liquid symbols (for both Claude and later filtering):
  - Calls `get_liquid_markets()` in `liquid.py`, which uses the Liquid SDK and returns `[{ symbol, max_leverage }, ...]`.
  - If the Liquid API or credentials are missing, `available_symbols` stays empty; the rest still runs.

---

### 4. Agent: Claude parses the request

- **File:** `agents.py` → `_claude_parse_request(prompt, available_symbols)`
- If `ANTHROPIC_API_KEY` is set, one Claude call is made with:
  - The user message
  - A short list of available Liquid symbols
- Claude returns JSON:
  - **`intent`**: `"markets"` | `"trade"` | `"general"`
  - **`search_terms`**: 2–8 words/phrases for filtering Polymarket (e.g. oil, crude, opec, wti)
  - **`liquid_symbols`**: 0–15 Liquid perp symbols that fit the theme (e.g. CL-PERP, GC-PERP)
- If Claude isn’t used or fails, `intent="general"`, `search_terms=[]`, `liquid_symbols=[]`.

---

### 5. Agent: Decide if we show markets

- **File:** `agents.py` → `run_agent()`
- `wants_data` is true if:
  - Claude said `intent` is `"markets"` or `"trade"`, or
  - The prompt contains keywords like "show", "list", "find", "markets", "oil", "crypto", "bets", etc.
- If not `wants_data`, the agent returns a short help message and no markets; flow stops.

---

### 6. Agent: Polymarket fetch and filter

- **File:** `agents.py` → `polymarket.py`
- **Fetch:** `fetch_events(limit=200)` → GET Gamma API `https://gamma-api.polymarket.com/events`, returns raw events.
- **Flatten:** `flatten_markets(events)` turns each event’s markets into a flat list with `event_title`, `question`, `market_id`, `condition_id`, `slug`, `yes_price`, `volume`, `clob_token_ids`, etc.
- **Filter:** `filter_by_query(all_markets, query, extra_terms)`:
  - Uses Claude’s `search_terms` when present (first term = `query`, rest = `extra_terms`).
  - Otherwise uses `_short_query_from_prompt(prompt)` and optionally `QUERY_EXPANSION` (e.g. "iran" → geopolit, fifa, oil).
  - Keeps markets whose title + question contain any of the terms.
- **Fallbacks:** If no match, tries each search term alone; if still none, returns top 30 markets by volume. Result is capped at 60, then 40 for display.

---

### 7. Agent: Liquid list for the batch

- **File:** `agents.py` → `liquid.py`
- **Symbols:** If Claude returned `liquid_symbols`, use those; else `_liquid_symbols_for_query()` (THEME_SYMBOLS map + default BTC, ETH, CL, GC).
- For each symbol in that set, find it in `all_liq_raw` and call `get_ticker(symbol)` for mark price and volume; build `liquid_list` with `symbol`, `max_leverage`, `mark_price`, `volume_24h`.
- If the API failed but we have symbols, append placeholder rows (no price/volume). List is capped at 25.

---

### 8. Agent: Optional Claude batch refinement

- **File:** `agents.py` → `_claude_select_batch(prompt, markets, liquid_list)`
- Second Claude call: given the current Polymarket and Liquid lists, Claude returns `polymarket_ids` and `liquid_symbols` to emphasize.
- Used only if Claude returns ≥5 Polymarket IDs or ≥3 Liquid symbols; otherwise the existing lists are kept to avoid over-narrowing.
- Final `markets` and `liquid_list` are trimmed to 40 and 25 items.

---

### 9. Agent: Response to frontend

- **File:** `agents.py` → `run_agent()`
- Returns:
  - `text`: Short summary (e.g. "Found N Polymarket markets. M Liquid perp(s) — set size and click Execute.")
  - `markets`: Polymarket list (with `market_id`, `question`, `yes_price`, `volume`, `slug`, `clob_token_ids`, etc.)
  - `liquid_markets`: Liquid list (symbol, mark_price, volume_24h, max_leverage)
  - `theme`: Label for the batch (e.g. "oil" or "Iran escalation")

---

### 10. Frontend: Render batch card

- **File:** `polymarket-agent-chat/frontend/src/App.jsx`
- Assistant message is appended with `text`, `markets`, `liquid_markets`, `theme`.
- **Batch grid:** Two columns.
  - **Polymarket:** `MarketsBlock` — table with Question, Yes %, Volume, Bet (Yes/No), Amount ($), Chart (link to `polymarket.com/event/{slug}`). Inline bar for Yes %.
  - **Liquid:** `LiquidBlock` — Batch budget ($), "Use suggested (equal split)", table with Symbol, Mark, Vol 24h, Side (Long/Short), Alloc %, Size ($), Leverage.
- State: `polymarketSelections[msgIndex][marketId] = { outcome, amount }`, `liquidSelections[msgIndex][symbol] = { side, size, leverage }`, `batchBudget[msgIndex]`.

---

### 11. User configures and clicks Execute

- User sets Polymarket bets (Yes/No + $) and Liquid orders (side, size, leverage), optionally "Use suggested (equal split)" from batch budget.
- When at least one Liquid size &gt; 0 or one Polymarket amount &gt; 0, an "Execute batch" button and allocation bar (Liquid vs Polymarket) appear.
- Clicking it calls `openConfirm(msgIndex, liquidOrders, polyOrders)`:
  - `liquidOrders` = rows with `size > 0` from `liquidSelections[msgIndex]`.
  - `polyOrders` = `buildPolymarketOrders(msg.markets, polymarketSelections[msgIndex])`: markets with `amount > 0`, mapping Yes/No to the correct `clob_token_ids` token and setting `price_limit` from yes_price + buffer or 0.99.

---

### 12. Confirmation modal

- **File:** `App.jsx` → `ConfirmModal`
- Shows counts and list of Liquid orders (Long/Short symbol $size leverage) and Polymarket bets ($amount).
- User confirms → `confirmExecute()`.

---

### 13. Execute API request

- **File:** `App.jsx` → `confirmExecute()`
- `POST /execute` with:
  - `liquid_orders`: `[{ symbol, side, size, leverage }]`
  - `polymarket_orders`: `[{ token_id, amount_usd, price_limit }]`

---

### 14. Backend execute endpoint

- **File:** `polymarket-agent-chat/backend/main.py` → `execute_endpoint(req: ExecuteRequest)`
- **Liquid:** For each `LiquidOrder`, calls `liquid.place_order(symbol, side, size, leverage)` (in `liquid.py` → SDK `place_order`). Appends `{ venue: "liquid", symbol, side, ...result }` or error.
- **Polymarket:** For each `PolymarketOrder`, calls `polymarket_clob.place_order(token_id, amount_usd, price_limit)` (in `polymarket_clob.py` → FOK market order via py-clob-client). Appends `{ venue: "polymarket", token_id, ...result }` or error.
- Returns `{ results: [...] }`.

---

### 15. Frontend: Show execution result

- **File:** `App.jsx` → `confirmExecute()`
- Response is stored on the assistant message as `executeResult`. Modal closes.
- `LiquidBlock` shows a Status column per symbol from `executeResult.results`. User sees success or error per order.

---

## File map

| Path | Role |
|------|------|
| `backend/main.py` | FastAPI app; `/agent` → `run_agent`, `/execute` → Liquid + Polymarket orders. |
| `backend/agents.py` | Orchestrates flow: Liquid symbols → Claude parse → Polymarket fetch/filter → Liquid list → optional Claude batch → response. |
| `backend/polymarket.py` | Gamma API: `fetch_events`, `flatten_markets`, `filter_by_query`. |
| `backend/liquid.py` | Liquid SDK: `get_liquid_markets`, `get_ticker`, `place_order`. |
| `backend/polymarket_clob.py` | Polymarket CLOB: `place_order` (FOK market order via private key + API creds). |
| `frontend/src/App.jsx` | Chat UI, batch grid (MarketsBlock + LiquidBlock), build orders, confirm modal, `/agent` and `/execute` calls. |
| `frontend/src/index.css` | Styles for chat, batch grid, allocation bar, modal. |
| `frontend/vite.config.js` | Proxy `/agent` and `/execute` to backend (e.g. port 8001). |

---

## APIs and env

- **Polymarket Gamma** (read): no auth; used in `polymarket.py`.
- **Polymarket CLOB** (trade): `POLY_API_KEY`, `POLY_API_SECRET`, `POLY_API_PASSPHRASE`, `POLY_PRIVATE_KEY` in `backend/.env`; used in `polymarket_clob.py`.
- **Liquid**: `LIQUID_API_KEY`, `LIQUID_API_SECRET` in `backend/.env`; used in `liquid.py`.
- **Claude**: `ANTHROPIC_API_KEY` in `backend/.env`; used in `agents.py` for request parsing and optional batch refinement.

`backend/main.py` loads `dotenv` so `.env` is applied.

---

## Run

```bash
# Backend (Python 3.9+)
cd polymarket-agent-chat/backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8001

# Frontend
cd polymarket-agent-chat/frontend
npm install
npm run dev
```

Open the frontend URL (e.g. http://localhost:5173). Ensure backend is on 8001 (or match `vite.config.js` proxy).

---

## Scope (MVP)

- [x] Fetch Polymarket events (Gamma) and Liquid markets; filter by theme.
- [x] Claude: parse any question → intent + search_terms + liquid_symbols; optional batch refinement.
- [x] Frontend: prompt bar, quick themes, batch card (Polymarket + Liquid), allocations, chart links.
- [x] Execute: one-click Liquid + Polymarket orders via `/execute`.
- [x] Env-based API keys (no hardcoded secrets).
