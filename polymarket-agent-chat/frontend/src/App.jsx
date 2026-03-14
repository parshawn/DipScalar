import { useState, useRef, useEffect } from 'react'

const API = ''

// ── Grid Loading Indicator ──
function GridLoader({ size = 'md', text }) {
  const s = size === 'sm' ? 32 : size === 'lg' ? 64 : 48
  const gap = size === 'sm' ? 2 : 3
  const cellSize = (s - gap * 2) / 3
  return (
    <div className="grid-loader">
      <div className="grid-loader-grid" style={{ width: s, height: s, gap, display: 'grid', gridTemplateColumns: `repeat(3, ${cellSize}px)` }}>
        {Array.from({ length: 9 }).map((_, i) => (
          <div
            key={i}
            className="grid-loader-cell"
            style={{ animationDelay: `${i * 0.1}s` }}
          />
        ))}
      </div>
      {text && <span className="grid-loader-text">{text}</span>}
    </div>
  )
}

const FALLBACK_THEMES = [
  { label: 'Politics', query: 'Show me politics markets' },
  { label: 'Crypto', query: 'Crypto perps and prediction markets' },
  { label: 'Sports', query: 'Sports prediction markets' },
  { label: 'Economy', query: 'Economy and Fed markets' },
  { label: 'Oil', query: 'Show me oil markets' },
  { label: 'Gold', query: 'Gold and silver markets' },
]


function fmtUsd(v) {
  if (v == null) return '—'
  const n = Number(v)
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`
  if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`
  if (n >= 1e3) return `$${(n / 1e3).toFixed(1)}K`
  return `$${n.toFixed(0)}`
}

function fmtPrice(v) {
  if (v == null) return '—'
  const n = Number(v)
  if (n >= 10000) return n.toLocaleString(undefined, { maximumFractionDigits: 0 })
  if (n >= 100) return n.toFixed(2)
  if (n >= 1) return n.toFixed(3)
  return n.toFixed(4)
}

// ── Mini Sparkline (Polymarket area chart) ──
function MiniSparkline({ data, color = '#2E5CFF', fillColor = 'rgba(46, 92, 255, 0.15)', onClick }) {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !data || data.length < 2) return
    const ctx = canvas.getContext('2d')
    const dpr = window.devicePixelRatio || 1
    const w = canvas.clientWidth
    const h = canvas.clientHeight
    canvas.width = w * dpr
    canvas.height = h * dpr
    ctx.scale(dpr, dpr)
    ctx.clearRect(0, 0, w, h)

    const values = data.map(d => d.value)
    const min = Math.min(...values)
    const max = Math.max(...values)
    const range = max - min || 1
    const padY = h * 0.1

    ctx.beginPath()
    data.forEach((d, i) => {
      const x = (i / (data.length - 1)) * w
      const y = h - padY - ((d.value - min) / range) * (h - padY * 2)
      if (i === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    })
    ctx.strokeStyle = color
    ctx.lineWidth = 1.5
    ctx.stroke()

    // Fill area
    const lastX = w
    const lastY = h - padY - ((values[values.length - 1] - min) / range) * (h - padY * 2)
    ctx.lineTo(lastX, h)
    ctx.lineTo(0, h)
    ctx.closePath()
    ctx.fillStyle = fillColor
    ctx.fill()
  }, [data, color, fillColor])

  return <canvas ref={canvasRef} style={{ width: '100%', height: '100%', display: 'block', cursor: 'pointer' }} onClick={onClick} />
}

// ── Sparkline wrappers (data passed in, no individual fetching) ──
function PolySparkline({ chartData, onClick }) {
  return (
    <div className={`market-card-chart ${chartData !== undefined ? '' : 'loading'}`}>
      {chartData && <MiniSparkline data={chartData} color="#2E5CFF" fillColor="rgba(46, 92, 255, 0.15)" onClick={onClick} />}
    </div>
  )
}

function LiquidSparkline({ chartData, onClick }) {
  return (
    <div className={`liquid-card-chart ${chartData !== undefined ? '' : 'loading'}`}>
      {chartData && <MiniSparkline data={chartData} color="#27AE60" fillColor="rgba(39, 174, 96, 0.15)" onClick={onClick} />}
    </div>
  )
}

// Parse raw price history into chart-ready data
function parsePolyHistory(history) {
  if (!history?.length) return null
  const pts = history
    .map(p => ({ time: Math.floor(Number(p.t)), value: Number(p.p) * 100 }))
    .filter(p => !isNaN(p.time) && !isNaN(p.value) && p.time > 0)
    .sort((a, b) => a.time - b.time)
  return pts.length >= 2 ? pts : null
}

function parseLiquidCandles(candles) {
  if (!candles?.length) return null
  const pts = candles
    .map(c => ({
      time: Math.floor(Number(c.t || c.timestamp)),
      value: Number(c.c || c.close),
      open: Number(c.o || c.open), high: Number(c.h || c.high),
      low: Number(c.l || c.low), close: Number(c.c || c.close),
    }))
    .filter(p => !isNaN(p.time) && !isNaN(p.value) && p.time > 0)
    .sort((a, b) => a.time - b.time)
  return pts.length >= 2 ? pts : null
}

// Batch-fetch all chart data for a message's markets in one parallel request
async function fetchBatchCharts(markets, liquidMarkets) {
  const polyTokens = []
  const tokenIdMap = {} // tokenId -> marketId
  for (const m of (markets || [])) {
    let ids = m.clob_token_ids || []
    if (typeof ids === 'string') try { ids = JSON.parse(ids) } catch { ids = [] }
    if (ids[0]) {
      polyTokens.push(ids[0])
      tokenIdMap[ids[0]] = m.market_id
    }
  }
  const liquidSymbols = (liquidMarkets || []).map(m => m.symbol).filter(Boolean)

  if (!polyTokens.length && !liquidSymbols.length) return {}

  try {
    const res = await fetch(`${API}/batch-charts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ poly_tokens: polyTokens, liquid_symbols: liquidSymbols }),
    })
    const data = await res.json()
    const chartCache = {}
    // Map poly data by tokenId
    for (const [tokenId, history] of Object.entries(data.poly || {})) {
      chartCache[`poly:${tokenId}`] = parsePolyHistory(history)
    }
    // Map liquid data by symbol
    for (const [symbol, candles] of Object.entries(data.liquid || {})) {
      chartCache[`liquid:${symbol}`] = parseLiquidCandles(candles)
    }
    return chartCache
  } catch {
    return {}
  }
}

// ── Full Chart (canvas-based for reliability) ──
function FullChart({ data, type, width, height }) {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !data || data.length < 2) return
    const ctx = canvas.getContext('2d')
    const dpr = window.devicePixelRatio || 1
    canvas.width = width * dpr
    canvas.height = height * dpr
    ctx.scale(dpr, dpr)
    ctx.clearRect(0, 0, width, height)

    const padT = 20, padB = 30, padL = 60, padR = 10
    const cw = width - padL - padR
    const ch = height - padT - padB

    if (type === 'candle') {
      // Candlestick chart
      const allHigh = data.map(d => d.high)
      const allLow = data.map(d => d.low)
      const min = Math.min(...allLow)
      const max = Math.max(...allHigh)
      const range = max - min || 1
      const barW = Math.max(1, (cw / data.length) * 0.7)
      const gap = cw / data.length

      // Grid lines
      ctx.strokeStyle = '#2A2E37'
      ctx.lineWidth = 0.5
      for (let i = 0; i <= 4; i++) {
        const y = padT + (ch / 4) * i
        ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(padL + cw, y); ctx.stroke()
        const val = max - (range / 4) * i
        ctx.fillStyle = '#858D98'
        ctx.font = '10px Inter, sans-serif'
        ctx.textAlign = 'right'
        ctx.fillText(fmtPrice(val), padL - 5, y + 3)
      }

      data.forEach((d, i) => {
        const x = padL + gap * i + gap / 2
        const oY = padT + ((max - d.open) / range) * ch
        const cY = padT + ((max - d.close) / range) * ch
        const hY = padT + ((max - d.high) / range) * ch
        const lY = padT + ((max - d.low) / range) * ch
        const up = d.close >= d.open
        const color = up ? '#27AE60' : '#E74C3C'

        // Wick
        ctx.strokeStyle = color
        ctx.lineWidth = 1
        ctx.beginPath(); ctx.moveTo(x, hY); ctx.lineTo(x, lY); ctx.stroke()

        // Body
        ctx.fillStyle = color
        const bodyTop = Math.min(oY, cY)
        const bodyH = Math.max(1, Math.abs(oY - cY))
        ctx.fillRect(x - barW / 2, bodyTop, barW, bodyH)
      })

      // Time labels
      ctx.fillStyle = '#858D98'
      ctx.font = '9px Inter, sans-serif'
      ctx.textAlign = 'center'
      const labelStep = Math.max(1, Math.floor(data.length / 6))
      data.forEach((d, i) => {
        if (i % labelStep === 0) {
          const x = padL + gap * i + gap / 2
          const date = new Date(d.time * 1000)
          const label = `${date.getMonth()+1}/${date.getDate()} ${String(date.getHours()).padStart(2,'0')}:${String(date.getMinutes()).padStart(2,'0')}`
          ctx.fillText(label, x, height - 8)
        }
      })
    } else {
      // Area/Line chart
      const values = data.map(d => d.value)
      const min = Math.min(...values)
      const max = Math.max(...values)
      const range = max - min || 1

      // Grid
      ctx.strokeStyle = '#2A2E37'
      ctx.lineWidth = 0.5
      for (let i = 0; i <= 4; i++) {
        const y = padT + (ch / 4) * i
        ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(padL + cw, y); ctx.stroke()
        const val = max - (range / 4) * i
        ctx.fillStyle = '#858D98'
        ctx.font = '10px Inter, sans-serif'
        ctx.textAlign = 'right'
        ctx.fillText(type === 'poly' ? `${val.toFixed(1)}%` : fmtPrice(val), padL - 5, y + 3)
      }

      // Line
      ctx.beginPath()
      data.forEach((d, i) => {
        const x = padL + (i / (data.length - 1)) * cw
        const y = padT + ((max - d.value) / range) * ch
        if (i === 0) ctx.moveTo(x, y)
        else ctx.lineTo(x, y)
      })
      ctx.strokeStyle = type === 'poly' ? '#2E5CFF' : '#27AE60'
      ctx.lineWidth = 2
      ctx.stroke()

      // Fill
      ctx.lineTo(padL + cw, padT + ch)
      ctx.lineTo(padL, padT + ch)
      ctx.closePath()
      ctx.fillStyle = type === 'poly' ? 'rgba(46, 92, 255, 0.1)' : 'rgba(39, 174, 96, 0.1)'
      ctx.fill()

      // Time labels
      ctx.fillStyle = '#858D98'
      ctx.font = '9px Inter, sans-serif'
      ctx.textAlign = 'center'
      const labelStep = Math.max(1, Math.floor(data.length / 6))
      data.forEach((d, i) => {
        if (i % labelStep === 0) {
          const x = padL + (i / (data.length - 1)) * cw
          const date = new Date(d.time * 1000)
          const label = `${date.getMonth()+1}/${date.getDate()} ${String(date.getHours()).padStart(2,'0')}:${String(date.getMinutes()).padStart(2,'0')}`
          ctx.fillText(label, x, height - 8)
        }
      })
    }
  }, [data, type, width, height])

  return <canvas ref={canvasRef} style={{ width, height, display: 'block' }} />
}

// ── Expanded Chart Modal ──
function ChartModal({ open, title, type, tokenId, symbol, onClose }) {
  const [data, setData] = useState(null)
  const [range, setRange] = useState(type === 'poly' ? '1d' : '1h')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open) { setData(null); return }
    setLoading(true)

    if (type === 'poly' && tokenId) {
      fetch(`${API}/prices-history?market=${encodeURIComponent(tokenId)}&interval=${range}`)
        .then(r => r.json())
        .then(d => {
          const history = d?.history || []
          const pts = history
            .map(p => ({ time: Math.floor(Number(p.t)), value: Number(p.p) * 100 }))
            .filter(p => !isNaN(p.time) && !isNaN(p.value) && p.time > 0)
            .sort((a, b) => a.time - b.time)
          setData(pts.length >= 2 ? pts : null)
          setLoading(false)
        })
        .catch(() => setLoading(false))
    } else if (type === 'liquid' && symbol) {
      const intervalMap = { '1h': ['1m', 60], '6h': ['5m', 72], '1d': ['15m', 96], '1w': ['1h', 168], '1m': ['4h', 180] }
      const [intv, lim] = intervalMap[range] || ['1h', 100]
      fetch(`${API}/candles?symbol=${encodeURIComponent(symbol)}&interval=${intv}&limit=${lim}`)
        .then(r => r.json())
        .then(d => {
          const candles = d?.candles || []
          const pts = candles
            .map(c => ({
              time: Math.floor(Number(c.t || c.timestamp)),
              open: Number(c.o || c.open), high: Number(c.h || c.high),
              low: Number(c.l || c.low), close: Number(c.c || c.close),
              value: Number(c.c || c.close),
            }))
            .filter(c => !isNaN(c.time) && c.time > 0 && !isNaN(c.close))
            .sort((a, b) => a.time - b.time)
          setData(pts.length >= 2 ? pts : null)
          setLoading(false)
        })
        .catch(() => setLoading(false))
    }
  }, [open, type, tokenId, symbol, range])

  useEffect(() => {
    if (!open) return
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  const ranges = ['1h', '6h', '1d', '1w', '1m']
  const chartType = type === 'liquid' ? 'candle' : 'poly'

  return (
    <div className="chart-modal-backdrop" onClick={onClose}>
      <div className="chart-modal" onClick={e => e.stopPropagation()}>
        <div className="chart-modal-header">
          <h3>{title}</h3>
          <button className="chart-modal-close" onClick={onClose}>✕</button>
        </div>
        <div className="chart-modal-ranges">
          {ranges.map(r => (
            <button key={r} className={range === r ? 'active' : ''} onClick={() => setRange(r)}>
              {r.toUpperCase()}
            </button>
          ))}
        </div>
        <div className="chart-modal-container">
          {loading && <div style={{ padding: '2rem', display: 'flex', justifyContent: 'center' }}><GridLoader size="md" text="Loading chart..." /></div>}
          {!loading && !data && <div style={{ color: '#505662', padding: '1rem', textAlign: 'center' }}>No data available</div>}
          {!loading && data && <FullChart data={data} type={chartType} width={650} height={350} />}
        </div>
      </div>
    </div>
  )
}

// ── Polymarket Market Card ──
function MarketCard({ market, selection, onSelect, chartData }) {
  const yesPct = market.yes_price != null ? market.yes_price * 100 : null
  const pctClass = yesPct != null ? (yesPct >= 60 ? 'high' : yesPct <= 40 ? 'low' : 'mid') : ''
  let tokenIds = market.clob_token_ids || []
  if (typeof tokenIds === 'string') {
    try { tokenIds = JSON.parse(tokenIds) } catch { tokenIds = [] }
  }
  if (!Array.isArray(tokenIds)) tokenIds = []
  const tokenId = tokenIds[0] || null
  const noPrice = market.yes_price != null ? ((1 - market.yes_price) * 100).toFixed(0) : null

  const [chartModal, setChartModal] = useState(false)

  return (
    <>
      <div className="market-card">
        <div className="market-card-question">{market.question || market.event_title}</div>
        <PolySparkline chartData={chartData} onClick={() => tokenId && setChartModal(true)} />
        <div className="market-card-stats">
          {yesPct != null && (
            <>
              <span className={`market-card-pct ${pctClass}`}>{yesPct.toFixed(1)}%</span>
              <div className="yes-bar">
                <div className={`yes-bar-fill ${pctClass}`} style={{ width: `${Math.min(100, Math.max(0, yesPct))}%` }} />
              </div>
            </>
          )}
          <span className="market-card-vol">{fmtUsd(market.volume)}</span>
        </div>
        {tokenIds.length >= 2 && (
          <div className="market-card-actions">
            <button
              className={`btn-yes ${selection.outcome === 'yes' ? 'active' : ''}`}
              onClick={() => onSelect({ ...selection, outcome: 'yes' })}
            >
              Yes {yesPct != null ? `${yesPct.toFixed(0)}¢` : ''}
            </button>
            <button
              className={`btn-no ${selection.outcome === 'no' ? 'active' : ''}`}
              onClick={() => onSelect({ ...selection, outcome: 'no' })}
            >
              No {noPrice != null ? `${noPrice}¢` : ''}
            </button>
            <div className="market-card-amount">
              <span>$</span>
              <input
                type="number"
                min={0}
                step={5}
                value={selection.amount || ''}
                onChange={e => onSelect({ ...selection, amount: parseFloat(e.target.value) || 0 })}
                placeholder="0"
              />
            </div>
          </div>
        )}
      </div>
      <ChartModal
        open={chartModal}
        title={market.question || market.event_title}
        type="poly"
        tokenId={tokenId}
        onClose={() => setChartModal(false)}
      />
    </>
  )
}

// ── Liquid Perp Card ──
function LiquidCard({ market, selection, onSelect, chartData }) {
  const [chartModal, setChartModal] = useState(false)

  return (
    <>
      <div className="liquid-card">
        <div className="liquid-card-header">
          <span className="liquid-card-symbol">{market.symbol}</span>
          <span className="liquid-card-price">{fmtPrice(market.mark_price)}</span>
        </div>
        <LiquidSparkline chartData={chartData} onClick={() => setChartModal(true)} />
        <div className="liquid-card-stats">
          <span>Vol 24h {fmtUsd(market.volume_24h)}</span>
          {market.max_leverage && <span>{market.max_leverage}x max</span>}
        </div>
        <div className="liquid-card-actions">
          <button
            className={`btn-long ${selection.side === 'buy' ? 'active' : ''}`}
            onClick={() => onSelect({ ...selection, side: 'buy' })}
          >
            Long ↑
          </button>
          <button
            className={`btn-short ${selection.side === 'sell' ? 'active' : ''}`}
            onClick={() => onSelect({ ...selection, side: 'sell' })}
          >
            Short ↓
          </button>
          <div className="liquid-card-inputs">
            <label>$</label>
            <input
              type="number"
              min={0}
              step={10}
              value={selection.size || ''}
              onChange={e => onSelect({ ...selection, size: parseFloat(e.target.value) || 0 })}
              placeholder="0"
            />
            <label>Lev</label>
            <input
              type="number"
              min={1}
              max={market.max_leverage || 50}
              value={selection.leverage || 1}
              onChange={e => onSelect({ ...selection, leverage: parseInt(e.target.value, 10) || 1 })}
            />
          </div>
        </div>
      </div>
      <ChartModal
        open={chartModal}
        title={market.symbol}
        type="liquid"
        symbol={market.symbol}
        onClose={() => setChartModal(false)}
      />
    </>
  )
}

// ── Polymarket Markets Block ──
function MarketsBlock({ msgIndex, markets, polySelections, onPolySel, chartCache }) {
  if (!markets?.length) return null
  const getSel = (mid) => polySelections[msgIndex]?.[mid] ?? { outcome: 'yes', amount: 0 }
  return (
    <div className="market-cards">
      {markets.map((m, i) => {
        let ids = m.clob_token_ids || []
        if (typeof ids === 'string') try { ids = JSON.parse(ids) } catch { ids = [] }
        const tokenId = ids[0] || null
        return (
          <MarketCard
            key={m.market_id || i}
            market={m}
            selection={getSel(m.market_id || i)}
            onSelect={(sel) => onPolySel(msgIndex, m.market_id || i, sel)}
            chartData={tokenId ? chartCache?.[`poly:${tokenId}`] : undefined}
          />
        )
      })}
    </div>
  )
}

// ── Liquid Block ──
function LiquidBlock({ msgIndex, markets, selections, budget, onBudget, onSelection, onUseSuggested, executing, executeResult, chartCache }) {
  if (!markets?.length) return null
  const getSel = (symbol) => selections[msgIndex]?.[symbol] ?? { side: 'buy', size: 0, leverage: 1 }
  const b = budget[msgIndex] ?? 0
  const resultBySymbol = executeResult?.results?.reduce((acc, r) => ({ ...acc, [r.symbol]: r }), {}) ?? {}

  return (
    <div className="liquid-block">
      <div className="batch-toolbar">
        <label>
          Budget ($)
          <input
            type="number"
            min={0}
            step={50}
            value={b || ''}
            onChange={e => onBudget(msgIndex, parseFloat(e.target.value) || 0)}
            placeholder="e.g. 500"
          />
        </label>
        <button type="button" className="btn-suggested" onClick={() => onUseSuggested(msgIndex, markets, b || 500)}>
          Equal split
        </button>
      </div>
      <div className="liquid-cards">
        {markets.map(m => {
          const sel = getSel(m.symbol)
          const res = resultBySymbol[m.symbol]
          return (
            <div key={m.symbol}>
              <LiquidCard
                market={m}
                selection={sel}
                onSelect={(s) => onSelection(msgIndex, m.symbol, s)}
                chartData={chartCache?.[`liquid:${m.symbol}`]}
              />
              {res && (
                <div className="exec-status">
                  {res.error
                    ? <span className="err" title={res.error}>✗ {res.error.slice(0, 30)}</span>
                    : <span className="ok">✓ {res.status ?? 'Filled'}</span>
                  }
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Confirm Modal ──
function ConfirmModal({ open, liquid_orders, polymarket_orders, onConfirm, onCancel, executing }) {
  if (!open) return null
  const liquidCount = liquid_orders?.length ?? 0
  const polyCount = polymarket_orders?.length ?? 0
  const total = liquidCount + polyCount
  const totalUsd = (liquid_orders || []).reduce((s, o) => s + (o.size || 0), 0) +
    (polymarket_orders || []).reduce((s, o) => s + (o.amount_usd || 0), 0)

  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <h3>Confirm Execution</h3>
        <p>{total} order(s) totaling {fmtUsd(totalUsd)}</p>
        {liquidCount > 0 && (
          <>
            <strong>Liquid ({liquidCount})</strong>
            <ul>
              {(liquid_orders || []).map((o, i) => (
                <li key={i}>{o.side === 'buy' ? 'Long' : 'Short'} {o.symbol} ${o.size} {o.leverage}x</li>
              ))}
            </ul>
          </>
        )}
        {polyCount > 0 && (
          <>
            <strong>Polymarket ({polyCount})</strong>
            <ul>
              {(polymarket_orders || []).map((o, i) => (
                <li key={i}>Bet ${o.amount_usd} @ max {(o.price_limit * 100).toFixed(0)}¢</li>
              ))}
            </ul>
          </>
        )}
        <div className="modal-actions">
          <button onClick={onCancel}>Cancel</button>
          <button className="btn-execute" disabled={executing} onClick={onConfirm}>
            {executing ? 'Executing…' : `Execute — ${fmtUsd(totalUsd)}`}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Batch Hero Card ──

// ── Main App ──
export default function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [liquidSelections, setLiquidSelections] = useState({})
  const [polymarketSelections, setPolymarketSelections] = useState({})
  const [batchBudget, setBatchBudget] = useState({})
  const [executing, setExecuting] = useState(false)
  const [confirmModal, setConfirmModal] = useState(null)
  const [chartCaches, setChartCaches] = useState({}) // msgIndex -> { "poly:tokenId": data, "liquid:symbol": data }
  const [trendingBatches, setTrendingBatches] = useState(null)
  const bottomRef = useRef(null)

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  // Fetch trending batches from Polymarket on mount
  useEffect(() => {
    fetch(`${API}/trending-batches`)
      .then(r => r.json())
      .then(d => setTrendingBatches(d.batches || []))
      .catch(() => setTrendingBatches([]))
  }, [])

  function setLiquidSel(msgIndex, symbol, sel) {
    setLiquidSelections(prev => ({ ...prev, [msgIndex]: { ...prev[msgIndex], [symbol]: sel } }))
  }

  function setBudgetVal(msgIndex, value) {
    setBatchBudget(prev => ({ ...prev, [msgIndex]: value }))
  }

  function useSuggested(msgIndex, markets, budget) {
    const n = markets.length
    const size = n > 0 ? budget / n : 0
    const next = { ...liquidSelections[msgIndex] }
    markets.forEach(m => {
      next[m.symbol] = { ...(next[m.symbol] ?? { side: 'buy', leverage: 1 }), size }
    })
    setLiquidSelections(prev => ({ ...prev, [msgIndex]: next }))
  }

  function setPolySel(msgIndex, marketId, sel) {
    setPolymarketSelections(prev => ({ ...prev, [msgIndex]: { ...prev[msgIndex], [marketId]: sel } }))
  }

  function buildPolymarketOrders(markets, polySel) {
    if (!markets?.length || !polySel) return []
    return markets
      .filter((m, idx) => {
        let ids = m.clob_token_ids || []
        if (typeof ids === 'string') try { ids = JSON.parse(ids) } catch { ids = [] }
        const s = polySel[m.market_id] ?? polySel[idx]
        return ids.length >= 2 && s?.amount > 0
      })
      .map((m, idx) => {
        let ids = m.clob_token_ids || []
        if (typeof ids === 'string') try { ids = JSON.parse(ids) } catch { ids = [] }
        const s = polySel[m.market_id] ?? polySel[idx]
        const tokenId = s.outcome === 'no' ? ids[1] : ids[0]
        const priceLimit = s.outcome === 'yes' && m.yes_price != null ? Math.min(0.99, m.yes_price + 0.05) : 0.99
        return { token_id: tokenId, amount_usd: s.amount, price_limit: priceLimit }
      })
  }

  function openConfirm(msgIndex, liquidOrders, polymarketOrders) {
    setConfirmModal({ msgIndex, liquid_orders: liquidOrders || [], polymarket_orders: polymarketOrders || [] })
  }

  async function confirmExecute() {
    if (!confirmModal) return
    const { msgIndex, liquid_orders: liquidOrders, polymarket_orders: polymarketOrders } = confirmModal
    setExecuting(true)
    try {
      const liquid_orders = (liquidOrders || []).map(o => ({ symbol: o.symbol, side: o.side, size: o.size, leverage: o.leverage || 1 }))
      const res = await fetch(`${API}/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ liquid_orders, polymarket_orders: polymarketOrders || [] }),
      })
      const data = await res.json()
      setMessages(m => {
        const next = [...m]
        if (next[msgIndex]?.role === 'assistant') next[msgIndex] = { ...next[msgIndex], executeResult: data }
        return next
      })
      setConfirmModal(null)
    } catch (e) {
      setMessages(m => {
        const next = [...m]
        if (next[msgIndex]?.role === 'assistant') next[msgIndex] = { ...next[msgIndex], executeResult: { error: e.message } }
        return next
      })
      setConfirmModal(null)
    } finally {
      setExecuting(false)
    }
  }

  async function send(promptOverride) {
    const prompt = (promptOverride ?? input).trim()
    if (!prompt || loading) return
    setInput('')
    setMessages(m => [...m, { role: 'user', content: prompt }])
    setLoading(true)
    try {
      const res = await fetch(`${API}/agent`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt }),
      })
      const data = await res.json()
      setMessages(m => {
        const newMsgs = [...m, {
          role: 'assistant',
          text: data.text ?? '',
          markets: data.markets ?? null,
          liquid_markets: data.liquid_markets ?? null,
          theme: data.theme ?? null,
        }]
        // Batch-fetch all chart data in parallel
        const msgIdx = newMsgs.length - 1
        fetchBatchCharts(data.markets, data.liquid_markets).then(cache => {
          setChartCaches(prev => ({ ...prev, [msgIdx]: cache }))
        })
        return newMsgs
      })
    } catch (e) {
      setMessages(m => [...m, { role: 'assistant', text: `Error: ${e.message}`, markets: null, liquid_markets: null }])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    const onKey = (e) => {
      if (confirmModal) {
        if (e.key === 'Escape') setConfirmModal(null)
        if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) confirmExecute()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [confirmModal])

  return (
    <div className="app">
      <header className="header">
        <h1>DipScalar</h1>
        <p>Cross-platform batch trading terminal</p>
      </header>

      <div className="chat">
        {messages.length === 0 && (
          <div className="placeholder">
            <p>Search markets or pick a trending category</p>
            {trendingBatches === null ? (
              <div className="batch-loading">Loading trending markets...</div>
            ) : trendingBatches.length > 0 ? (
              <div className="batch-cards-grid">
                {trendingBatches.map(b => (
                  <div key={b.label} className="batch-hero-card" onClick={() => !loading && send(`Show me ${b.label} markets`)}>
                    <div className="batch-card-header">
                      {b.image && <img src={b.image} alt={b.label} className="batch-card-img" />}
                      <div>
                        <div className="batch-card-title">{b.label}</div>
                        <div className="batch-card-subtitle">{b.top_event}</div>
                      </div>
                    </div>
                    <div className="batch-card-meta">
                      <span className="poly-count">{b.event_count} event(s)</span>
                      <span className="liq-count">{fmtUsd(b.total_volume)} volume</span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="batch-cards-grid">
                {FALLBACK_THEMES.map(t => (
                  <div key={t.label} className="batch-hero-card" onClick={() => !loading && send(t.query)}>
                    <div className="batch-card-header">
                      <div><div className="batch-card-title">{t.label}</div></div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`msg ${msg.role}`}>
            <span className="role">{msg.role === 'user' ? 'You' : 'Agent'}</span>
            {msg.role === 'user' ? (
              <div className="content">{msg.content}</div>
            ) : (
              <>
                <div className="content">{msg.text}</div>
                <div className="batch-grid">
                  <div className="batch-col">
                    <div className="batch-label">Polymarket{msg.theme ? ` — ${msg.theme}` : ''}</div>
                    <MarketsBlock msgIndex={i} markets={msg.markets} polySelections={polymarketSelections} onPolySel={setPolySel} chartCache={chartCaches[i]} />
                  </div>
                  <div className="batch-col">
                    <div className="batch-label">Liquid Perps{msg.theme ? ` — ${msg.theme}` : ''}</div>
                    <LiquidBlock
                      msgIndex={i}
                      markets={msg.liquid_markets}
                      selections={liquidSelections}
                      budget={batchBudget}
                      onBudget={setBudgetVal}
                      onSelection={setLiquidSel}
                      onUseSuggested={useSuggested}
                      executing={executing}
                      executeResult={msg.executeResult}
                      chartCache={chartCaches[i]}
                    />
                  </div>
                </div>
                {(() => {
                  const liquidOrders = (msg.liquid_markets || [])
                    .filter(m => (liquidSelections[i]?.[m.symbol]?.size || 0) > 0)
                    .map(m => ({ symbol: m.symbol, ...liquidSelections[i][m.symbol] }))
                  const polyOrders = buildPolymarketOrders(msg.markets, polymarketSelections[i])
                  const hasAny = liquidOrders.length > 0 || polyOrders.length > 0
                  const total = liquidOrders.reduce((s, o) => s + (o.size || 0), 0) +
                    polyOrders.reduce((s, o) => s + (o.amount_usd || 0), 0)
                  const segments = total > 0 ? [
                    ...liquidOrders.map(o => ({
                      key: `liq-${o.symbol}`, label: o.symbol, venue: 'liquid', share: (o.size || 0) / total,
                    })),
                    ...polyOrders.map((o, idx) => ({
                      key: `poly-${idx}`, label: 'PM', venue: 'polymarket', share: (o.amount_usd || 0) / total,
                    })),
                  ] : []
                  return hasAny ? (
                    <div className="batch-execute-row">
                      <div className="pre-exec-summary">
                        <div className="alloc-bar">
                          {segments.map(seg => (
                            <div
                              key={seg.key}
                              className={`alloc-seg ${seg.venue}`}
                              style={{ flex: seg.share }}
                              title={`${seg.venue === 'liquid' ? 'Liquid' : 'Polymarket'} ${seg.label} ${(seg.share * 100).toFixed(0)}%`}
                            />
                          ))}
                        </div>
                        <div className="alloc-legend">
                          {liquidOrders.length > 0 && <span className="liquid-tag">Liquid: {liquidOrders.length} order(s)</span>}
                          {polyOrders.length > 0 && <span className="poly-tag">Polymarket: {polyOrders.length} bet(s)</span>}
                        </div>
                      </div>
                      <button
                        type="button"
                        className="execute-btn"
                        disabled={executing}
                        onClick={() => openConfirm(i, liquidOrders, polyOrders)}
                      >
                        Execute Batch — {fmtUsd(total)}
                      </button>
                    </div>
                  ) : null
                })()}
                {msg.executeResult?.error && (
                  <div className="content execute-result err">{msg.executeResult.error}</div>
                )}
              </>
            )}
          </div>
        ))}

        {loading && (
          <div className="msg assistant">
            <span className="role">Agent</span>
            <GridLoader size="sm" text="Searching markets..." />
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="input-row">
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !e.shiftKey && send()}
          placeholder="Search markets or describe a trade..."
          disabled={loading}
        />
        <button onClick={() => send()} disabled={loading || !input.trim()}>Send</button>
      </div>

      <ConfirmModal
        open={confirmModal !== null}
        liquid_orders={confirmModal?.liquid_orders}
        polymarket_orders={confirmModal?.polymarket_orders}
        onConfirm={confirmExecute}
        onCancel={() => setConfirmModal(null)}
        executing={executing}
      />
    </div>
  )
}
