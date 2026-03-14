# DipScalar Implementation Plan

> Hackathon tracks: **Liquid Trading ($8k)** + **Polymarket Bonus ($2k)**

---

## Table of Contents

1. [Current State](#current-state)
2. [Phase 1 — Charts](#phase-1--charts)
3. [Phase 2 — Premade Batch Suggestions](#phase-2--premade-batch-suggestions)
4. [Phase 3 — UI Polish (Polymarket Terminal)](#phase-3--ui-polish-polymarket-terminal)
5. [API Reference](#api-reference)
6. [File Map](#file-map)

---

## Current State

### What exists
- **Backend** (`backend/`): FastAPI with `/agent` and `/execute` endpoints
  - `agents.py` — Claude-powered prompt parsing, Polymarket fetch/filter, Liquid symbol matching
  - `polymarket.py` — Gamma API client (fetch events, flatten markets, keyword filter)
  - `liquid.py` — Liquid SDK client (`get_markets`, `get_ticker`, `place_order`)
  - `polymarket_clob.py` — Polymarket CLOB order execution (FOK market orders)
  - `main.py` — FastAPI app, CORS, request models

- **Frontend** (`frontend/`): React 18 + Vite, zero UI libraries
  - `App.jsx` — Chat UI, `MarketsBlock` (Polymarket table), `LiquidBlock` (Liquid perps table), `ConfirmModal`, batch execution flow
  - `index.css` — Dark theme, 2-column grid layout, allocation bar

### What's missing
1. **No charts** — markets show a single price point; "Chart" column just links to polymarket.com
2. **No premade batches** — quick themes send a prompt but don't pre-populate matched markets
3. **UI feels generic** — doesn't look like Polymarket's polished trading terminal

---

## Phase 1 — Charts

### Goal
Inline mini-charts for every market row: probability sparklines for Polymarket, price lines for Liquid perps. Click to expand full chart.

### 1.1 Backend: Price History Endpoints

#### Polymarket Price History
**Source:** Polymarket CLOB API — no auth required for this endpoint.

```
GET https://clob.polymarket.com/prices-history
```

| Param | Type | Required | Notes |
|-------|------|----------|-------|
| `market` | string | Yes | The **token ID** (asset ID from `clob_token_ids[0]`) — NOT the `market_id` |
| `startTs` | number | No | Unix timestamp (seconds) |
| `endTs` | number | No | Unix timestamp (seconds) |
| `interval` | string | No | `1h`, `6h`, `1d`, `1w`, `1m`, `max`, `all` |
| `fidelity` | int | No | Accuracy in minutes, default 1 |

**Response:**
```json
{
  "history": [
    { "t": 1710000000, "p": 0.65 },
    { "t": 1710003600, "p": 0.67 }
  ]
}
```

- `t` = unix timestamp (seconds)
- `p` = price (0–1, represents YES probability)

**New backend endpoint:**

```python
# main.py — add this endpoint
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
```

#### Liquid Candles
**Source:** Liquid SDK — `client.get_candles(symbol, interval, limit)`

```
GET https://api-public.liquidmax.xyz/v1/markets/{symbol}/candles
```

| Param | Type | Required | Notes |
|-------|------|----------|-------|
| `symbol` | string (path) | Yes | e.g. `BTC-PERP` |
| `interval` | string (query) | No | `1m`, `5m`, `15m`, `30m`, `1h`, `4h`, `1d` (default `1h`) |
| `limit` | int (query) | No | 1–1000, default 100 |
| `start` | number (query) | No | Unix seconds |
| `end` | number (query) | No | Unix seconds |

**Response:** Array of OHLCV candles:
```json
[
  { "timestamp": 1710000000, "open": 64200.5, "high": 64500.0, "low": 64100.0, "close": 64350.0, "volume": 1250000 }
]
```

**New backend endpoint:**

```python
# main.py — add this endpoint
@app.get("/candles")
async def candles(symbol: str, interval: str = "1h", limit: int = 100):
    """Get OHLCV candles from Liquid SDK."""
    from liquid import _client
    import asyncio
    c = _client()
    if not c:
        return {"candles": []}
    def _get():
        result = c.get_candles(symbol, interval=interval, limit=limit)
        return [
            {"t": getattr(candle, "timestamp", None), "o": getattr(candle, "open", None),
             "h": getattr(candle, "high", None), "l": getattr(candle, "low", None),
             "c": getattr(candle, "close", None), "v": getattr(candle, "volume", None)}
            for candle in (result or [])
        ]
    data = await asyncio.to_thread(_get)
    return {"candles": data}
```

**Update `vite.config.js`** to proxy new endpoints:
```javascript
proxy: {
  '/agent': 'http://127.0.0.1:8001',
  '/execute': 'http://127.0.0.1:8001',
  '/prices-history': 'http://127.0.0.1:8001',
  '/candles': 'http://127.0.0.1:8001',
}
```

### 1.2 Frontend: Chart Library

**Choice: `lightweight-charts` by TradingView**
- ~40KB gzipped, purpose-built for financial data
- Supports line charts (Polymarket probability), candlestick charts (Liquid), area charts
- Looks professional out of the box (dark theme built-in)
- Zero config needed for good-looking charts

```bash
cd frontend && npm install lightweight-charts
```

### 1.3 Frontend: Mini Charts in Market Rows

#### Polymarket mini sparkline
- On mount / when markets data arrives, fetch `/prices-history?market={clob_token_ids[0]}&interval=1d` for each market
- Render as a tiny **area chart** (80×32px) inline in the table row
- Line color: `#2E5CFF` (Poly Blue), area fill: semi-transparent `rgba(46, 92, 255, 0.1)`
- Click → expand to a full-width chart modal with time range selector (1H, 6H, 1D, 1W, 1M)

#### Liquid mini sparkline
- On mount, fetch `/candles?symbol={symbol}&interval=1h&limit=24` for each Liquid symbol
- Render as a tiny **line chart** (80×32px) using close prices
- Line color: `#22c55e` (green for long) or adapt to current side selection
- Click → expand to full candlestick chart modal

#### Batch fetch strategy (avoid rate limits)
- Fetch chart data in parallel batches of 5, with 200ms delay between batches
- Cache results in a `useRef` map so re-renders don't re-fetch
- Show a tiny loading skeleton (pulsing gray bar) while fetching

### 1.4 Frontend: Expanded Chart Modal

When user clicks a mini chart:
- Full-width modal (600×400px) with `lightweight-charts` chart
- **Polymarket**: Area chart, Y axis 0–100% probability, time range buttons
- **Liquid**: Candlestick chart with volume histogram, time range buttons
- Time ranges: 1H, 6H, 1D, 1W, 1M — each fetches fresh data from the API
- Dark theme matching the app palette
- Close on Escape or clicking backdrop

---

## Phase 2 — Premade Batch Suggestions

### Goal
Show curated "recommended batches" as hero cards on the landing state. Each batch pairs specific Polymarket markets with Liquid perps for a coherent trade thesis.

### 2.1 Backend: Curated Batches Endpoint

Create a new file `backend/batches.py`:

```python
"""Premade batch suggestions — curated market + perps combos."""

CURATED_BATCHES = [
    {
        "id": "oil-hedge",
        "title": "Oil Shock",
        "subtitle": "Geopolitical oil exposure",
        "icon": "🛢️",
        "thesis": "Oil supply disruption play. Polymarket events on Middle East + oil prices, hedged with CL-PERP.",
        "polymarket_queries": ["oil", "crude", "opec", "energy"],
        "liquid_symbols": ["CL-PERP", "GC-PERP"],
        "default_side": "buy",
    },
    {
        "id": "crypto-bull",
        "title": "Crypto Bull",
        "subtitle": "Long crypto conviction",
        "icon": "₿",
        "thesis": "Bullish crypto across prediction markets and perps. BTC/ETH/SOL longs with Polymarket crypto event exposure.",
        "polymarket_queries": ["bitcoin", "btc", "ethereum", "crypto", "sec"],
        "liquid_symbols": ["BTC-PERP", "ETH-PERP", "SOL-PERP"],
        "default_side": "buy",
    },
    {
        "id": "election-play",
        "title": "Election Play",
        "subtitle": "US political markets",
        "icon": "🗳️",
        "thesis": "Election and policy prediction markets. Paired with macro perps that move on political outcomes.",
        "polymarket_queries": ["trump", "election", "president", "republican", "democrat", "congress"],
        "liquid_symbols": ["BTC-PERP", "GC-PERP"],
        "default_side": "buy",
    },
    {
        "id": "gold-safety",
        "title": "Gold Safety",
        "subtitle": "Flight to safety",
        "icon": "🥇",
        "thesis": "Gold and silver long as safe haven. Paired with recession/rate cut prediction markets.",
        "polymarket_queries": ["gold", "fed", "rate", "recession", "inflation"],
        "liquid_symbols": ["GC-PERP", "SI-PERP"],
        "default_side": "buy",
    },
    {
        "id": "iran-escalation",
        "title": "Iran Escalation",
        "subtitle": "Middle East conflict exposure",
        "icon": "🌍",
        "thesis": "Iran/Israel conflict play. Oil goes up on escalation, gold as hedge, prediction markets on conflict outcomes.",
        "polymarket_queries": ["iran", "israel", "middle east", "escalat", "geopolit"],
        "liquid_symbols": ["CL-PERP", "GC-PERP"],
        "default_side": "buy",
    },
    {
        "id": "degen-basket",
        "title": "Degen Basket",
        "subtitle": "High-volume, high-volatility",
        "icon": "🎰",
        "thesis": "Top trending markets by volume + leveraged crypto perps. Maximum exposure to market momentum.",
        "polymarket_queries": [],  # Empty = top by volume
        "liquid_symbols": ["BTC-PERP", "ETH-PERP", "SOL-PERP"],
        "default_side": "buy",
    },
]
```

**New endpoint in `main.py`:**

```python
@app.get("/batches")
async def get_batches():
    """Return curated batch suggestions with live market data."""
    from batches import CURATED_BATCHES
    from polymarket import fetch_events, flatten_markets, filter_by_query
    from liquid import get_ticker

    events = await fetch_events(limit=200)
    all_markets = flatten_markets(events)

    result = []
    for batch in CURATED_BATCHES:
        # Get matching Polymarket markets
        poly_markets = []
        for q in batch["polymarket_queries"]:
            poly_markets.extend(filter_by_query(all_markets, q))
        if not poly_markets:
            poly_markets = sorted(all_markets, key=lambda m: float(m.get("volume") or 0), reverse=True)[:15]
        # Deduplicate by market_id
        seen = set()
        deduped = []
        for m in poly_markets:
            mid = m.get("market_id")
            if mid not in seen:
                seen.add(mid)
                deduped.append(m)
        poly_markets = deduped[:15]

        # Get Liquid tickers
        liquid_markets = []
        for sym in batch["liquid_symbols"]:
            try:
                tick = await get_ticker(sym)
                liquid_markets.append({
                    "symbol": sym,
                    "mark_price": tick.get("mark_price") if tick else None,
                    "volume_24h": tick.get("volume_24h") if tick else None,
                })
            except:
                liquid_markets.append({"symbol": sym, "mark_price": None, "volume_24h": None})

        result.append({
            **batch,
            "polymarket_count": len(poly_markets),
            "liquid_count": len(liquid_markets),
            "markets": poly_markets,
            "liquid_markets": liquid_markets,
        })
    return {"batches": result}
```

**Update `vite.config.js`** to proxy `/batches`.

### 2.2 Frontend: Batch Cards on Landing

Replace the current placeholder/example prompts with hero batch cards:

```
┌─────────────────────────────────────────┐
│  🛢️ Oil Shock        ₿ Crypto Bull     │
│  5 markets · 2 perps  8 mkts · 3 perps │
│  [Load Batch]         [Load Batch]      │
├─────────────────────────────────────────┤
│  🗳️ Election Play    🥇 Gold Safety    │
│  12 markets · 2 perps 6 mkts · 2 perps │
│  [Load Batch]         [Load Batch]      │
├─────────────────────────────────────────┤
│  🌍 Iran Escalation  🎰 Degen Basket   │
│  7 markets · 2 perps  15 mkts · 3 perps│
│  [Load Batch]         [Load Batch]      │
└─────────────────────────────────────────┘
```

Each card shows:
- Icon + title + subtitle
- Thesis (1-line)
- Count of Polymarket markets + Liquid perps
- "Load Batch" button → populates the chat with a pre-built assistant message containing the full market data (same format as agent response)

### 2.3 Frontend: Load Batch Flow

When user clicks "Load Batch":
1. Fetch `/batches` (or use cached data from initial load on mount)
2. Insert an assistant message with the batch's `markets` and `liquid_markets` directly — no agent call needed
3. Charts auto-fetch for the loaded markets
4. User can immediately configure amounts and execute

---

## Phase 3 — UI Polish (Polymarket Terminal)

### Goal
Transform the generic dark chat UI into a recognizable Polymarket-style trading terminal that blends both Liquid and Polymarket visually.

### 3.1 Design Tokens (Polymarket Palette)

```css
:root {
  /* Backgrounds */
  --bg-primary: #131518;        /* Page background (deep blue-black) */
  --bg-surface: #1C2026;        /* Card/panel backgrounds */
  --bg-elevated: #252A33;       /* Hover states, active panels */
  --bg-input: #1A1D23;          /* Input fields */

  /* Brand */
  --accent-blue: #2E5CFF;       /* Polymarket Poly Blue — primary actions, chart lines */
  --accent-blue-hover: #4A74FF;

  /* Semantic */
  --color-yes: #27AE60;         /* Yes / Long / positive */
  --color-yes-bg: rgba(39, 174, 96, 0.1);
  --color-no: #E74C3C;          /* No / Short / negative */
  --color-no-bg: rgba(231, 76, 60, 0.1);

  /* Text */
  --text-primary: #FFFFFF;
  --text-secondary: #858D98;
  --text-muted: #505662;

  /* Borders */
  --border: #2A2E37;
  --border-hover: #3A3F4A;

  /* Typography */
  --font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}
```

### 3.2 Typography

Add Inter font via Google Fonts in `index.html`:
```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
```

### 3.3 Layout Redesign

**Current:** 900px max-width chat with 2-column grid inside messages

**New:** Full-width terminal layout

```
┌──────────────────────────────────────────────────────┐
│  DipScalar                              [wallet/acct]│
│  ─────────────────────────────────────────────────── │
│  [Oil] [Crypto] [Iran] [Trump] [Gold] [Degen]       │
│                                                      │
│  ┌──── Polymarket ─────────┬──── Liquid Perps ──────┐│
│  │ ┌─────────────────────┐ │ ┌────────────────────┐ ││
│  │ │ Question    Yes  📈 │ │ │ Symbol  Mark   📈  │ ││
│  │ │ Will BTC.. 62%  ~~~ │ │ │ BTC-P  64.2k  ~~~ │ ││
│  │ │ Will ETH.. 45%  ~~~ │ │ │ ETH-P   3.1k  ~~~ │ ││
│  │ │ [Yes 62¢] [No 38¢] │ │ │ [Long] [Short]     │ ││
│  │ └─────────────────────┘ │ └────────────────────┘ ││
│  └─────────────────────────┴────────────────────────┘│
│                                                      │
│  ┌─ Allocation ──────────────────────────────────── ┐│
│  │ ████████████░░░░░░ Liquid 60% | Polymarket 40%  ││
│  │ Total: $500         [Execute Batch]              ││
│  └──────────────────────────────────────────────────┘│
│                                                      │
│  [Ask about markets...]                     [Send ➜] │
└──────────────────────────────────────────────────────┘
```

### 3.4 Component Redesign Details

#### Header
- Title: "DipScalar" in Inter 700, white
- Subtitle: "Cross-platform batch trading terminal" in `--text-secondary`
- Remove chat-style header, make it a proper terminal header with border-bottom

#### Theme Chips → Pill Tabs
- Rounded pill buttons with `--bg-surface` background
- Active state: `--accent-blue` background, white text
- Show a count badge (e.g., "Oil · 5") when loaded

#### Market Cards (Polymarket)
Replace the dense table with card-based rows:

```
┌────────────────────────────────────────────────┐
│ Will Bitcoin reach $100k by June 2026?         │
│ ~~~~ [sparkline chart 120×40] ~~~~             │
│                                                │
│  62.3%                     Vol $1.2M           │
│  ██████████░░░░░                               │
│                                                │
│  [Yes 62¢]  [No 38¢]    Amount: [$___]        │
└────────────────────────────────────────────────┘
```

- **Question** as the title (bold, white)
- **Sparkline** below the title — area chart, Poly Blue
- **Yes percentage** large, with a progress bar
- **Yes/No buttons** as colored pills: green filled for Yes, red outlined for No
  - Format: "Yes 62¢" / "No 38¢" (prices summing to ~$1)
- **Volume** in compact format ($1.2M, $450K)
- **Amount input** inline

#### Liquid Perps Cards
Similar card-based rows:

```
┌────────────────────────────────────────────────┐
│ BTC-PERP                          Mark $64,200 │
│ ~~~~ [sparkline chart 120×40] ~~~~             │
│                                                │
│  Vol 24h $12.5M        Funding +0.01%          │
│                                                │
│  [Long ↑]  [Short ↓]   Size: [$___]  Lev: [5x]│
└────────────────────────────────────────────────┘
```

- **Symbol** as title
- **Sparkline** — line chart from candle close prices
- **Long/Short buttons** as colored pills (green/red)
- **Size + leverage** inline

#### Yes/No Buttons (Polymarket Style)
```css
.btn-yes {
  background: var(--color-yes);
  color: white;
  border: none;
  border-radius: 20px;
  padding: 6px 16px;
  font-weight: 600;
  font-size: 0.85rem;
}
.btn-no {
  background: transparent;
  color: var(--color-no);
  border: 2px solid var(--color-no);
  border-radius: 20px;
  padding: 6px 16px;
  font-weight: 600;
  font-size: 0.85rem;
}
/* Active state — filled */
.btn-yes.active { background: var(--color-yes); box-shadow: 0 0 12px rgba(39,174,96,0.3); }
.btn-no.active { background: var(--color-no); color: white; }
```

#### Allocation Bar
- Keep the current segment bar concept but make it taller (12px) with rounded corners
- Add dollar amounts inside each segment
- Green = Liquid, Poly Blue = Polymarket

#### Execute Button
- Full-width at bottom of batch card
- `--accent-blue` background (Poly Blue), not green
- "Execute Batch — $500" with total amount displayed

#### Input Bar
- Bottom-fixed, full-width
- `--bg-surface` background, `--border` border
- Blue send button with arrow icon
- Placeholder: "Search markets or describe a trade..."

#### Confirm Modal
- `--bg-surface` background with `--border` border
- Rounded 16px corners
- Blue "Execute" button (matching Polymarket CTA style)

### 3.5 Responsive Breakpoints

```css
/* Desktop: 2-column side-by-side */
@media (min-width: 1024px) {
  .batch-grid { grid-template-columns: 1fr 1fr; }
  .app { max-width: 1200px; }
}

/* Tablet: stacked */
@media (max-width: 1023px) {
  .batch-grid { grid-template-columns: 1fr; }
}

/* Mobile: compact cards */
@media (max-width: 599px) {
  .market-card { padding: 0.75rem; }
  .mini-chart { display: none; }  /* Hide sparklines on mobile */
}
```

---

## API Reference

### Polymarket APIs

| API | Base URL | Auth | Used For |
|-----|----------|------|----------|
| **Gamma API** | `https://gamma-api.polymarket.com` | None | Fetching events/markets, no auth needed |
| **CLOB API** | `https://clob.polymarket.com` | API key + private key for orders; none for price history | Price history, order placement |
| **Data API** | `https://data-api.polymarket.com` | None | User positions, trades (not used yet) |

**Key Polymarket Endpoints:**
- `GET /events` (Gamma) — fetch active events with markets
- `GET /prices-history` (CLOB) — historical price data for charts
- `POST /order` (CLOB, authenticated) — place orders

**Docs:** https://docs.polymarket.com
**Full docs index:** https://docs.polymarket.com/llms.txt
**Python SDK:** https://github.com/Polymarket/py-clob-client
**TypeScript SDK:** https://github.com/Polymarket/clob-client
**MCP Server:** https://docs.polymarket.com/mcp

### Liquid APIs

| Resource | URL | Notes |
|----------|-----|-------|
| **REST API** | `https://api-public.liquidmax.xyz/v1` | HMAC-SHA256 signed |
| **SDK docs** | https://sdk.tryliquid.xyz/docs/sdk | Full Python SDK reference |
| **API reference** | https://sdk.tryliquid.xyz/docs/api-reference | All REST endpoints |
| **Quickstart** | https://sdk.tryliquid.xyz/docs/quickstart | Setup guide |
| **MCP server** | https://sdk.tryliquid.xyz/docs/mcp | AI agent integration |

**Key Liquid SDK Methods:**
```python
from liquidtrading import LiquidClient

client = LiquidClient(api_key="lq_...", api_secret="sk_...")

# Market data
client.get_markets()                                    # All symbols
client.get_ticker("BTC-PERP")                          # Mark price, volume, funding
client.get_orderbook("BTC-PERP", depth=20)             # L2 snapshot
client.get_candles("BTC-PERP", interval="1h", limit=100)  # OHLCV candles

# Account
client.get_account()                                    # Equity, margin, balance
client.get_positions()                                  # Open positions with PnL

# Orders
client.place_order(symbol="BTC-PERP", side="buy", type="market", size=100, leverage=5)
client.place_order(symbol="BTC-PERP", side="buy", type="limit", size=100, price=64000, leverage=5, tp=65000, sl=63000)
client.get_open_orders()
client.cancel_order(order_id)
client.cancel_all_orders()

# Positions
client.close_position("BTC-PERP")                     # Full close
client.close_position("BTC-PERP", size=0.01)           # Partial close (coin units)
client.set_tp_sl("BTC-PERP", tp=65000, sl=63000)
client.update_leverage("BTC-PERP", leverage=10)
```

**Candle intervals:** `1m`, `5m`, `15m`, `30m`, `1h`, `4h`, `1d`

**SDK install:** `pip install liquidtrading-python`

**Auth:** `LIQUID_API_KEY` (format: `lq_...`) + `LIQUID_API_SECRET` (format: `sk_...`)

### Charting Library

**lightweight-charts (TradingView)**
- npm: `npm install lightweight-charts`
- Docs: https://tradingview.github.io/lightweight-charts/
- ~40KB gzipped
- Supports: Line, Area, Candlestick, Bar, Histogram, Baseline charts
- Built-in dark theme
- React usage: create a ref div, call `createChart()` on mount

---

## File Map

### Current files (to modify)

| File | Changes |
|------|---------|
| `backend/main.py` | Add `/prices-history`, `/candles`, `/batches` endpoints |
| `backend/liquid.py` | Add `get_candles()` wrapper |
| `backend/polymarket.py` | No changes needed (Gamma API already sufficient) |
| `backend/agents.py` | No changes needed |
| `frontend/src/App.jsx` | Major rewrite: card layout, chart components, batch cards, new buttons |
| `frontend/src/index.css` | Complete restyle to Polymarket palette |
| `frontend/vite.config.js` | Add proxy for `/prices-history`, `/candles`, `/batches` |
| `frontend/index.html` | Add Inter font link |
| `frontend/package.json` | Add `lightweight-charts` dependency |

### New files to create

| File | Purpose |
|------|---------|
| `backend/batches.py` | Curated batch definitions (CURATED_BATCHES list) |

---

## Implementation Order

```
Phase 1 (Charts)          Phase 3 (UI Polish)          Phase 2 (Batches)
─────────────────         ──────────────────          ─────────────────
1. Backend endpoints      4. Polymarket palette       7. batches.py
2. npm install charts     5. Card-based layout        8. /batches endpoint
3. Mini sparklines +      6. Yes/No pills,            9. Hero batch cards
   expanded chart modal      Long/Short buttons,      10. Load batch flow
                             allocation bar,
                             Inter font, responsive
```

**Recommended build order:** Phase 1 → Phase 3 → Phase 2

Charts and UI polish make the biggest visual impact for the demo. Premade batches are a UX cherry on top that builds on the polished UI.

**Estimated new dependencies:**
- Frontend: `lightweight-charts` (only addition)
- Backend: none (already has `httpx` for proxying CLOB, `liquidtrading-python` for candles)