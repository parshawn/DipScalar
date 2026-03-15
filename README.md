# DipScalar

**Cross-platform batch trading terminal combining Polymarket prediction markets with Liquid perpetual futures.**

DipScalar lets you search for any market theme using natural language — "show me Venezuela markets", "hedge against inflation", "crypto bull run" — and instantly see relevant prediction markets and tradeable perpetual futures side-by-side. Build a thematic batch and execute trades across both platforms in one click.

![Dark terminal UI](https://img.shields.io/badge/UI-Dark_Terminal-131518?style=flat-square) ![Python](https://img.shields.io/badge/Backend-Python_3.11-3776AB?style=flat-square&logo=python&logoColor=white) ![React](https://img.shields.io/badge/Frontend-React_18-61DAFB?style=flat-square&logo=react&logoColor=black) ![Claude](https://img.shields.io/badge/AI-Claude_Haiku-D97757?style=flat-square)

---

## What It Does

1. **Type any theme** into the chatbot — "oil markets", "Venezuela", "hedge against inflation", "crypto bull run"
2. **AI agent interprets your intent** and searches across both Polymarket and Liquid simultaneously
3. **View grouped results** — prediction markets collapsed by event with sparkline charts, perpetual futures with live prices and leverage info
4. **Configure your batch** — set Yes/No positions on prediction markets, Long/Short on perps, adjust sizes and leverage
5. **Execute everything in one click** — trades are placed on both venues simultaneously

---

## How It Works

### The Core Loop

```
User prompt ──► Claude Haiku parses intent + generates search terms
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
  Polymarket Gamma API    Liquid SDK (~370 symbols)
  /public-search          get_markets() + get_ticker()
  (server-side search)    (crypto, commodities, stocks, indices)
        │                       │
        └───────────┬───────────┘
                    ▼
        Group by event, deduplicate,
        merge into themed batch
                    │
                    ▼
        Frontend renders cards with
        sparklines, prices, trade controls
                    │
                    ▼
        POST /execute ──► simultaneous orders
        on Polymarket CLOB + Liquid
```

### Architecture

```
┌─────────────────────────────────────────────────┐
│                   Frontend                       │
│            React 18 + Vite 5 + Three.js          │
│                                                  │
│  ┌─────────┐  ┌──────────┐  ┌────────────────┐  │
│  │ Chat UI │  │ Market   │  │ Chart Modals   │  │
│  │ (Input) │  │ Cards    │  │ (Canvas-based) │  │
│  └────┬────┘  └────┬─────┘  └───────┬────────┘  │
└───────┼────────────┼────────────────┼────────────┘
        │            │                │
        ▼            ▼                ▼
┌─────────────────────────────────────────────────┐
│                 Backend (FastAPI)                 │
│                                                  │
│  POST /agent ──► Agent Orchestrator              │
│       │          (Claude Haiku parsing)           │
│       │              │                            │
│       │    ┌─────────┴──────────┐                │
│       │    ▼                    ▼                 │
│       │  Polymarket           Liquid              │
│       │  Gamma API            SDK                 │
│       │  /public-search       get_markets()       │
│       │  (server-side)        get_ticker()        │
│       │                                           │
│  POST /execute ──► Place orders on both venues    │
│  POST /batch-charts ──► Parallel chart data fetch │
│  GET  /trending-batches ──► Category discovery    │
│  GET  /candles ──► Liquid OHLCV data              │
│  GET  /prices-history ──► Polymarket price data   │
└─────────────────────────────────────────────────┘
```

---

## Tech Stack

### Backend — Python / FastAPI

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Web Framework** | [FastAPI](https://fastapi.tiangolo.com/) | Async REST API with automatic OpenAPI docs |
| **AI Agent** | [Claude Haiku](https://docs.anthropic.com/) (claude-haiku-4-5) via Anthropic SDK | Natural language parsing, search term generation, symbol matching |
| **Polymarket Data** | [Gamma API](https://docs.polymarket.com/) (`gamma-api.polymarket.com`) | Server-side market search via `/public-search`, event discovery — no auth needed |
| **Polymarket Trading** | [CLOB API](https://docs.polymarket.com/) via `py-clob-client` | Order placement (requires API keys + private key for on-chain signing) |
| **Liquid Data + Trading** | [`liquidtrading-python`](https://pypi.org/project/liquidtrading-python/) SDK v0.1.3 | ~370 perpetual futures — crypto, commodities, stocks, indices. Routes through Hyperliquid |
| **HTTP Client** | [httpx](https://www.python-httpx.org/) | Async HTTP requests to external APIs |
| **Environment** | [python-dotenv](https://pypi.org/project/python-dotenv/) | Secure credential management from `.env` |
| **Server** | [Uvicorn](https://www.uvicorn.org/) | ASGI server with hot-reload |
| **Container** | Docker (Python 3.11-slim) | Production deployment |

### Frontend — React / Vite

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Framework** | [React 18](https://react.dev/) | Component-based UI |
| **Build Tool** | [Vite 5](https://vitejs.dev/) | Fast HMR, dev proxy to backend |
| **3D Background** | [Three.js](https://threejs.org/) | Animated dotted wave surface on landing page |
| **Charts** | Pure HTML5 Canvas | Sparklines and expanded candlestick/area charts |
| **Styling** | Vanilla CSS with CSS variables | Dark trading terminal theme, glassmorphic effects |
| **Font** | [Inter](https://fonts.google.com/specimen/Inter) (Google Fonts) | Clean, readable typography for financial data |

### Deployment

| Service | Purpose |
|---------|---------|
| **Vercel** | Frontend static hosting (React build output) |
| **Railway** | Backend container hosting (Docker / FastAPI) |
| **Supabase** | Database (user state, watchlists, order history — if needed) |

---

## Backend Implementation

### Agent Orchestrator (`agents.py`)

The core intelligence layer. When a user sends a message, this is what happens:

**Step 1: Claude Haiku Parsing** (`_claude_parse_request()`)

Sends the user prompt + all ~370 available Liquid symbols to Claude Haiku in one call. Claude returns:
- `intent`: "markets", "trade", or "general"
- `search_terms`: 10-20 keywords including topic words, related people, places, actions, and multi-word phrases
- `liquid_symbols`: Exact symbols from the available list that relate to the query

For example, "show me Venezuela markets" produces:
```json
{
  "intent": "markets",
  "search_terms": ["venezuela", "venezuelan", "maduro", "machado", "caracas", "invade", "coup", "sanctions", "oil production", "exile"],
  "liquid_symbols": ["xyz:CL", "flx:OIL", "cash:WTI"]
}
```

**Step 2: Server-Side Polymarket Search**

Uses the Gamma API `/public-search` endpoint with multiple search terms queried in parallel. Results are merged and deduplicated by event slug. This replaced the original approach of fetching 500 events and filtering client-side — which missed most results since Polymarket has ~9,000 events.

**Step 3: Liquid Symbol Resolution**

Two-layer validation to prevent hallucinated symbols:
1. `_liquid_symbols_for_query()` does fuzzy matching against real available symbols (exact match for short tickers, substring only if both are 4+ chars to prevent "nfl" matching "nflx")
2. Claude's picks are validated against fuzzy results

**Step 4: Event Grouping**

Markets are grouped by parent event title. Each group shows the top market by volume with an expand button to see all outcomes. "2026 FIFA World Cup Winner" with 50+ outcome markets becomes one collapsible card.

**Step 5: Liquid Deduplication**

The same asset often exists across multiple Liquid providers (e.g. `xyz:GOLD`, `cash:GOLD`, `km:GOLD`, `flx:GOLD`, `hyna:GOLD`). A ticker alias map normalizes these, and only the highest-volume provider is kept.

### Polymarket Client (`polymarket.py`)

Three search strategies:
- **`search_events(query)`** — Uses `/public-search` for server-side text search with pagination
- **`fetch_events_by_tag(tag_slug)`** — Fetches events by Polymarket tag (e.g. "venezuela", "crypto")
- **`filter_by_query(markets, query)`** — Client-side regex filter with word-boundary matching. Short terms (<4 chars) use strict boundaries (`\bnfl\b`) to avoid "nfl" matching "inflation". Longer terms use prefix-matching (`\binflat`) so "inflation" matches "inflationary"

### Liquid Client (`liquid.py`)

Wraps the `liquidtrading-python` SDK with async support via `asyncio.to_thread()`:
- **`get_liquid_markets()`** — Returns all ~370 available symbols with max leverage
- **`get_ticker(symbol)`** — Live mark price, 24h volume, funding rate
- **`get_candles(symbol)`** — OHLCV candlestick data
- **`place_order(symbol, side, size, leverage)`** — Market order execution

Liquid symbols span multiple providers and asset classes:
```
Crypto:       BTC-PERP, ETH-PERP, SOL-PERP, DOGE-PERP, ...
Commodities:  xyz:CL, flx:OIL, cash:WTI, flx:GOLD, xyz:SILVER, ...
Stocks:       xyz:NVDA, km:AAPL, cash:TSLA, xyz:AMZN, ...
Indices:      flx:USA500, km:USTECH, xyz:XYZ100, km:JPN225, ...
Thematic:     vntl:DEFENSE, vntl:NUCLEAR, vntl:SPACEX, vntl:BIOTECH, ...
```

### Polymarket CLOB Client (`polymarket_clob.py`)

Handles order placement on Polymarket via the `py-clob-client` SDK:
- Uses Fill-Or-Kill (FOK) market orders
- Requires API key, secret, passphrase, and a private key for on-chain signing (Polygon network)
- Each order specifies a `token_id` (identifying Yes/No outcome), `amount_usd`, and `price_limit` (slippage)

### API Endpoints (`main.py`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/agent` | POST | Main chat endpoint — sends prompt, returns grouped markets + liquid perps |
| `/execute` | POST | Batch trade execution — places orders on both Polymarket and Liquid |
| `/batch-charts` | POST | Parallel chart data fetch for all visible markets in one request |
| `/trending-batches` | GET | Top Polymarket categories by volume (Politics, Sports, Crypto, Economy, etc.) |
| `/batches` | GET | Curated batch suggestions with live Liquid ticker data |
| `/prices-history` | GET | Proxy to Polymarket CLOB price history |
| `/candles` | GET | Liquid OHLCV candle data |

---

## Frontend Implementation

### Component Architecture (`App.jsx`)

**Landing Page:**
- Three.js animated dotted wave surface (`DottedSurface.jsx`) — blue-tinted dots that animate upward on load and slide down when the user sends their first message
- Trending category cards fetched from `/trending-batches` — clickable to pre-fill the search
- Glassmorphic auto-resizing textarea with backdrop blur

**Results View:**
- **`EventGroup`** — Collapsible card for a Polymarket event. Shows event title, outcome count, total volume. Blue left border accent when expanded. Contains child `MarketCard` components
- **`MarketCard`** — Individual prediction market outcome. Question, yes price %, green Yes/red No pill buttons, amount input, sparkline chart
- **`LiquidCard`** — Perpetual futures card. Symbol, mark price, 24h volume, max leverage. Long/Short buttons, size input, leverage selector
- **`MiniSparkline`** — Pure canvas sparkline with gradient fill. Area chart for Polymarket (0-100%), line chart for Liquid
- **`ChartModal`** — Expanded chart view with time range selector (1H/4H/1D/1W). Area charts for Polymarket, candlestick for Liquid
- **`ShimmerText`** — CSS wave animation for "Searching the markets..." loading state

**Charts:**
We initially used TradingView's `lightweight-charts` library (tried both v4 and v5) but encountered persistent rendering issues. We switched to pure HTML5 Canvas rendering which works reliably. All chart data is fetched via a single batch request (`POST /batch-charts`) rather than individually per card, significantly improving load times.

### Styling (`index.css`)

Dark trading terminal theme:
```css
--bg-primary: #131518;      /* Main background */
--bg-surface: #1C2026;      /* Card surfaces */
--bg-elevated: #252A33;     /* Elevated elements */
--accent-blue: #2E5CFF;     /* Primary accent */
--color-yes: #27AE60;       /* Yes/Long — green */
--color-no: #E74C3C;        /* No/Short — red */
```

Key visual features:
- Glassmorphic input bar with backdrop blur
- Event groups with left accent border when expanded, nested background for child markets
- Smooth expand/collapse transitions
- Responsive: 2-column grid on desktop, stacked on mobile

### Three.js Background (`DottedSurface.jsx`)

Animated particle field using `THREE.Points` with blue-tinted dots arranged in a grid. The surface undulates with a sine-wave animation. On initial load, the surface animates upward from below the viewport. When the user sends their first message, it slides down and out of view.

---

## Search Quality

Search went through several iterations to handle edge cases:

| Problem | Root Cause | Fix |
|---------|-----------|-----|
| Only 1 result for "Venezuela" when Polymarket has 35+ events | Fetching 500 events out of 9,000 and filtering client-side | Switched to Gamma API `/public-search` for server-side text search |
| "nfl" matching "inflation" | Simple substring matching | Word-boundary regex (`\bnfl\b` for short terms, `\binflat` prefix for 4+ chars) |
| Claude generating overly academic search terms like "CPI inflation forecast" | Prompt didn't specify terms must match actual market titles | Updated prompt to require simple words, people names, places, actions |
| 5 identical gold contracts showing | Same asset from multiple Liquid providers | Ticker alias map + dedup by underlying, keeping highest volume |
| Netflix (NFLX) showing for "football" | Claude hallucinating symbol relevance | Fuzzy matcher validates Claude's picks; strict rules prevent "nfl" → "nflx" |

---

## Environment Variables

Create a `.env` file in `polymarket-agent-chat/backend/`:

```env
# Required — AI-powered search term generation
ANTHROPIC_API_KEY=sk-ant-...

# Required — Liquid perpetual futures data + trading
LIQUID_API_KEY=...
LIQUID_API_SECRET=...

# Optional — Polymarket trading (not needed for read-only market data)
POLY_API_KEY=...
POLY_API_SECRET=...
POLY_API_PASSPHRASE=...
POLY_PRIVATE_KEY=...
```

**Note:** Polymarket market data (Gamma API) requires no authentication. Polymarket trading (CLOB API) requires all four `POLY_*` variables including a private key for on-chain signing on Polygon.

---

## Running Locally

### Prerequisites
- Python 3.11+
- Node.js 18+
- API keys (see Environment Variables above)

### Backend

```bash
cd polymarket-agent-chat/backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Create .env with your API keys (see above)
uvicorn main:app --reload --port 8000
```

### Frontend

```bash
cd polymarket-agent-chat/frontend
npm install
npm run dev
# Runs on http://localhost:5173
# Vite proxies API requests to backend on :8000
```

Open **http://localhost:5173** and start typing queries.

---

## Deployment

### Frontend → Vercel

```bash
cd polymarket-agent-chat/frontend
npm run build    # outputs to dist/
# Deploy dist/ to Vercel, set VITE_API_URL env var to Railway backend URL
```

### Backend → Railway

The included `Dockerfile` builds a production container:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

Set all environment variables in Railway's dashboard.

---

## Project Structure

```
polymarket-agent-chat/
├── backend/
│   ├── main.py              # FastAPI app — all API endpoints
│   ├── agents.py            # AI agent orchestrator (Claude Haiku)
│   ├── polymarket.py        # Gamma API client — search, events, filtering
│   ├── polymarket_clob.py   # CLOB API client — order placement
│   ├── liquid.py            # Liquid SDK wrapper — markets, tickers, candles, orders
│   ├── batches.py           # Curated batch definitions
│   ├── requirements.txt     # Python dependencies
│   ├── Dockerfile           # Production container
│   └── .env                 # API keys (not committed)
├── frontend/
│   ├── src/
│   │   ├── App.jsx          # Main app — all UI components
│   │   ├── DottedSurface.jsx# Three.js animated background
│   │   ├── index.css        # Global styles, dark theme
│   │   └── main.jsx         # React entry point
│   ├── index.html           # HTML shell with Inter font
│   ├── vite.config.js       # Vite config with API proxy
│   └── package.json         # Node dependencies
├── .gitignore
└── README.md
```

---

## Example Queries

| Query | What You Get |
|-------|-------------|
| "Show me Venezuela markets" | 30+ Polymarket events (invasion, leadership, elections, oil production) + crude oil perps |
| "Hedge against inflation" | Fed rate cut markets, CPI, recession predictions + gold, silver, bond perps |
| "Crypto bull run" | Bitcoin/ETH price prediction markets + BTC-PERP, ETH-PERP, SOL-PERP with leverage |
| "Oil markets" | OPEC, crude oil price, energy policy predictions + WTI, Brent, natural gas perps |
| "Football" | NFL Draft, Super Bowl, team matchup predictions (no false positives like Netflix) |

---

Built for the **Liquid Trading** ($8K) and **Polymarket Bonus** ($2K) hackathon tracks.
