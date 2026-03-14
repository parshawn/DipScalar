import { useState, useRef, useEffect } from 'react'

const API = ''

const QUICK_THEMES = [
  { label: 'Oil', query: 'Show me oil markets', icon: '🛢️' },
  { label: 'Crypto', query: 'Crypto perps for a long bias', icon: '₿' },
  { label: 'Iran', query: 'Iran escalation batch', icon: '🌍' },
  { label: 'Trump', query: 'Trump prediction markets', icon: '🗳️' },
  { label: 'Gold', query: 'Gold and silver perps', icon: '🥇' },
]

const EXAMPLE_PROMPTS = [
  'Show me oil markets',
  'List crypto prediction markets',
  'Iran escalation batch',
  'What Liquid perps match gold?',
]

function themeIcon(prompt) {
  if (!prompt) return ''
  const p = (prompt || '').toLowerCase()
  if (p.includes('oil')) return '🛢️'
  if (p.includes('crypto') || p.includes('btc') || p.includes('eth')) return '₿'
  if (p.includes('iran') || p.includes('geopolit')) return '🌍'
  if (p.includes('trump')) return '🗳️'
  if (p.includes('gold') || p.includes('silver')) return '🥇'
  return '📊'
}

function MarketsBlock({ msgIndex, markets, polySelections, onPolySel }) {
  if (!markets?.length) return null
  const getSel = (mid) => polySelections[msgIndex]?.[mid] ?? { outcome: 'yes', amount: 0 }
  return (
    <div className="markets-block">
      <table>
        <thead>
          <tr>
            <th>Question</th>
            <th>Yes %</th>
            <th>Volume</th>
            <th>Bet</th>
            <th>Amount ($)</th>
            <th>Chart</th>
          </tr>
        </thead>
        <tbody>
          {markets.map((m, i) => {
            const ids = m.clob_token_ids && Array.isArray(m.clob_token_ids) ? m.clob_token_ids : []
            const sel = getSel(m.market_id || i)
            const yesPct = m.yes_price != null ? (m.yes_price * 100) : null
            const slug = m.slug
            const marketUrl = slug
              ? `https://polymarket.com/event/${encodeURIComponent(slug)}`
              : 'https://polymarket.com'
            return (
              <tr key={m.market_id || i}>
                <td>{m.question || m.event_title}</td>
                <td className="num">
                  {yesPct != null ? `${yesPct.toFixed(1)}%` : '—'}
                  {yesPct != null && (
                    <div className="yes-bar">
                      <div
                        className={`yes-bar-fill ${
                          yesPct >= 60 ? 'high' : yesPct <= 40 ? 'low' : 'mid'
                        }`}
                        style={{ width: `${Math.min(100, Math.max(0, yesPct))}%` }}
                      />
                    </div>
                  )}
                </td>
                <td className="num">{m.volume != null ? Number(m.volume).toLocaleString(undefined, { maximumFractionDigits: 0 }) : '—'}</td>
                <td>
                  {ids.length >= 2 ? (
                    <select value={sel.outcome} onChange={(e) => onPolySel(msgIndex, m.market_id || i, { ...sel, outcome: e.target.value })}>
                      <option value="yes">Yes</option>
                      <option value="no">No</option>
                    </select>
                  ) : '—'}
                </td>
                <td>
                  {ids.length >= 2 ? (
                    <input
                      type="number"
                      min={0}
                      step={5}
                      value={sel.amount || ''}
                      onChange={(e) => onPolySel(msgIndex, m.market_id || i, { ...sel, amount: parseFloat(e.target.value) || 0 })}
                      placeholder="0"
                    />
                  ) : '—'}
                </td>
                <td>
                  {marketUrl ? (
                    <button
                      type="button"
                      className="chart-link"
                      onClick={() => window.open(marketUrl, '_blank', 'noopener,noreferrer')}
                    >
                      View
                    </button>
                  ) : '—'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function LiquidBlock({
  msgIndex,
  markets,
  selections,
  budget,
  onBudget,
  onSelection,
  onUseSuggested,
  executing,
  executeResult,
}) {
  if (!markets?.length) return null
  const getSel = (symbol) => selections[msgIndex]?.[symbol] ?? { side: 'buy', size: 0, leverage: 1 }
  const b = budget[msgIndex] ?? 0
  const orders = markets.filter((m) => (getSel(m.symbol).size || 0) > 0)
  const totalNotional = orders.reduce((sum, m) => sum + (getSel(m.symbol).size || 0), 0)
  const avgLeverage = orders.length ? orders.reduce((s, m) => s + (getSel(m.symbol).leverage || 1), 0) / orders.length : 0
  const estMargin = avgLeverage > 0 ? totalNotional / avgLeverage : 0
  const summary = orders.map((m) => {
    const s = getSel(m.symbol)
    return `${s.side === 'buy' ? 'Long' : 'Short'} ${m.symbol} $${s.size || 0} ${s.leverage || 1}x`
  })
  const resultBySymbol = executeResult?.results?.reduce((acc, r) => ({ ...acc, [r.symbol]: r }), {}) ?? {}

  return (
    <div className="liquid-block">
      <div className="batch-toolbar">
        <label>
          Batch budget ($)
          <input
            type="number"
            min={0}
            step={50}
            value={b || ''}
            onChange={(e) => onBudget(msgIndex, parseFloat(e.target.value) || 0)}
            placeholder="e.g. 500"
          />
        </label>
        <button type="button" className="btn-suggested" onClick={() => onUseSuggested(msgIndex, markets, b || 500)}>
          Use suggested (equal split)
        </button>
      </div>
      <table>
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Mark</th>
            <th>Vol 24h</th>
            <th>Side</th>
            <th>Alloc %</th>
            <th>Size ($)</th>
            <th>Leverage</th>
            {executeResult && <th>Status</th>}
          </tr>
        </thead>
        <tbody>
          {markets.map((m) => {
            const s = getSel(m.symbol)
            const res = resultBySymbol[m.symbol]
            const allocPct = b > 0 && (s.size > 0) ? ((s.size / b) * 100).toFixed(0) : (s.allocationPct ?? '')
            return (
              <tr key={m.symbol} className={s.side === 'buy' ? 'long' : 'short'}>
                <td>{m.symbol}</td>
                <td className="num">{m.mark_price != null ? Number(m.mark_price).toFixed(2) : '—'}</td>
                <td className="num">{m.volume_24h != null ? Number(m.volume_24h).toLocaleString(undefined, { maximumFractionDigits: 0 }) : '—'}</td>
                <td>
                  <select value={s.side} onChange={(e) => onSelection(msgIndex, m.symbol, { ...s, side: e.target.value })}>
                    <option value="buy">Long</option>
                    <option value="sell">Short</option>
                  </select>
                </td>
                <td>
                  <input
                    type="number"
                    min={0}
                    max={100}
                    step={5}
                    value={allocPct}
                    onChange={(e) => {
                      const pct = parseFloat(e.target.value) || 0
                      const newSize = b > 0 ? (b * pct) / 100 : 0
                      onSelection(msgIndex, m.symbol, { ...s, allocationPct: pct, size: newSize })
                    }}
                    placeholder="%"
                  />
                </td>
                <td>
                  <input
                    type="number"
                    min={0}
                    step={10}
                    value={s.size || ''}
                    onChange={(e) => {
                      const v = parseFloat(e.target.value) || 0
                      onSelection(msgIndex, m.symbol, { ...s, size: v, allocationPct: b > 0 ? (v / b) * 100 : undefined })
                    }}
                    placeholder="0"
                  />
                </td>
                <td>
                  <input type="number" min={1} max={50} value={s.leverage || 1} onChange={(e) => onSelection(msgIndex, m.symbol, { ...s, leverage: parseInt(e.target.value, 10) || 1 })} />
                </td>
                {executeResult && (
                  <td className="exec-status">
                    {res ? (
                      res.error ? (
                        <span className="err" title={res.error}>✗ {res.error.slice(0, 20)}</span>
                      ) : (
                        <span className="ok">✓ {res.status ?? 'Done'}</span>
                      )
                    ) : (
                      '—'
                    )}
                  </td>
                )}
              </tr>
            )
          })}
        </tbody>
      </table>
      {orders.length > 0 && (
        <>
          <div className="pre-exec-summary">
            <strong>Liquid:</strong> {summary.join(' · ')} — Total notional ${totalNotional.toFixed(0)}, est. margin ~${estMargin.toFixed(0)}
          </div>
        </>
      )}
    </div>
  )
}

function ConfirmModal({ open, liquid_orders, polymarket_orders, onConfirm, onCancel, executing }) {
  if (!open) return null
  const liquidCount = liquid_orders?.length ?? 0
  const polyCount = polymarket_orders?.length ?? 0
  const total = liquidCount + polyCount
  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>Confirm execution</h3>
        <p>Place {total} order(s):</p>
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
                <li key={i}>Bet ${o.amount_usd} @ max price {o.price_limit}</li>
              ))}
            </ul>
          </>
        )}
        <div className="modal-actions">
          <button type="button" onClick={onCancel}>Cancel</button>
          <button type="button" className="btn-execute" disabled={executing} onClick={onConfirm}>
            {executing ? 'Executing…' : 'Execute'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [liquidSelections, setLiquidSelections] = useState({})
  const [polymarketSelections, setPolymarketSelections] = useState({})
  const [batchBudget, setBatchBudget] = useState({})
  const [executing, setExecuting] = useState(false)
  const [confirmModal, setConfirmModal] = useState(null)
  const bottomRef = useRef(null)

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  function setLiquidSel(msgIndex, symbol, sel) {
    setLiquidSelections((prev) => ({
      ...prev,
      [msgIndex]: { ...prev[msgIndex], [symbol]: sel },
    }))
  }

  function setBudget(msgIndex, value) {
    setBatchBudget((prev) => ({ ...prev, [msgIndex]: value }))
  }

  function useSuggested(msgIndex, markets, budget) {
    const n = markets.length
    const pct = n > 0 ? 100 / n : 0
    const size = n > 0 ? budget / n : 0
    const next = { ...liquidSelections[msgIndex] }
    markets.forEach((m) => {
      next[m.symbol] = { ...(next[m.symbol] ?? { side: 'buy', leverage: 1 }), allocationPct: pct, size }
    })
    setLiquidSelections((prev) => ({ ...prev, [msgIndex]: next }))
  }

  function setPolySel(msgIndex, marketId, sel) {
    setPolymarketSelections((prev) => ({
      ...prev,
      [msgIndex]: { ...prev[msgIndex], [marketId]: sel },
    }))
  }

  function buildPolymarketOrders(markets, polySel) {
    if (!markets?.length || !polySel) return []
    return markets
      .filter((m, idx) => {
        const ids = m.clob_token_ids && Array.isArray(m.clob_token_ids) ? m.clob_token_ids : []
        const s = polySel[m.market_id] ?? polySel[idx]
        return ids.length >= 2 && s?.amount > 0
      })
      .map((m, idx) => {
        const ids = m.clob_token_ids
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
      const liquid_orders = (liquidOrders || []).map((o) => ({ symbol: o.symbol, side: o.side, size: o.size, leverage: o.leverage || 1 }))
      const res = await fetch(`${API}/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ liquid_orders, polymarket_orders: polymarketOrders || [] }),
      })
      const data = await res.json()
      setMessages((m) => {
        const next = [...m]
        const msg = next[msgIndex]
        if (msg && msg.role === 'assistant') next[msgIndex] = { ...msg, executeResult: data }
        return next
      })
      setConfirmModal(null)
    } catch (e) {
      setMessages((m) => {
        const next = [...m]
        const msg = next[msgIndex]
        if (msg && msg.role === 'assistant') next[msgIndex] = { ...msg, executeResult: { error: e.message } }
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
    setMessages((m) => [...m, { role: 'user', content: prompt }])
    setLoading(true)
    try {
      const res = await fetch(`${API}/agent`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt }),
      })
      const data = await res.json()
      setMessages((m) => [
        ...m,
        {
          role: 'assistant',
          text: data.text ?? '',
          markets: data.markets ?? null,
          liquid_markets: data.liquid_markets ?? null,
          theme: data.theme ?? null,
        },
      ])
    } catch (e) {
      setMessages((m) => [
        ...m,
        { role: 'assistant', text: `Error: ${e.message}`, markets: null, liquid_markets: null },
      ])
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
        <h1>Polymarket Agent</h1>
        <p>Ask for market data or use a theme below. Set batch budget and execute Liquid orders from the batch card.</p>
      </header>

      <div className="quick-themes">
        {QUICK_THEMES.map((t) => (
          <button
            key={t.label}
            type="button"
            className="chip"
            onClick={() => send(t.query)}
            disabled={loading}
          >
            <span className="chip-icon">{t.icon}</span> {t.label}
          </button>
        ))}
      </div>

      <div className="chat">
        {messages.length === 0 && (
          <div className="placeholder">
            <p>Try an example or type your own:</p>
            <div className="example-prompts">
              {EXAMPLE_PROMPTS.map((text) => (
                <button key={text} type="button" className="example-pill" onClick={() => send(text)}>
                  {text}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`msg ${msg.role}`}>
            <span className="role">
              {msg.role === 'user' ? 'You' : 'Agent'}
              {msg.role === 'assistant' && msg.liquid_markets?.length > 0 && (
                <span className="theme-badge" title={messages[i - 1]?.content}>{themeIcon(messages[i - 1]?.content)}</span>
              )}
            </span>
            {msg.role === 'user' ? (
              <div className="content">{msg.content}</div>
            ) : (
              <>
                <div className="content">{msg.text}</div>
                <div className="batch-grid">
                  <div className="batch-col">
                    <div className="batch-label">Polymarket{msg.theme ? ` — ${msg.theme}` : ''}</div>
                    <MarketsBlock msgIndex={i} markets={msg.markets} polySelections={polymarketSelections} onPolySel={setPolySel} />
                  </div>
                  <div className="batch-col">
                    <div className="batch-label">Liquid perps{msg.theme ? ` — ${msg.theme}` : ''}</div>
                    <LiquidBlock
                      msgIndex={i}
                      markets={msg.liquid_markets}
                      selections={liquidSelections}
                      budget={batchBudget}
                      onBudget={setBudget}
                      onSelection={setLiquidSel}
                      onUseSuggested={useSuggested}
                      executing={executing}
                      executeResult={msg.executeResult}
                    />
                  </div>
                </div>
                {(() => {
                  const liquidOrders = (msg.liquid_markets || []).filter((m) => (liquidSelections[i]?.[m.symbol]?.size || 0) > 0).map((m) => ({ symbol: m.symbol, ...liquidSelections[i][m.symbol] }))
                  const polyOrders = buildPolymarketOrders(msg.markets, polymarketSelections[i])
                  const hasAny = liquidOrders.length > 0 || polyOrders.length > 0
                  const total = liquidOrders.reduce((s, o) => s + (o.size || 0), 0) + polyOrders.reduce((s, o) => s + (o.amount_usd || 0), 0)
                  const segments = total > 0 ? [
                    ...liquidOrders.map((o) => ({
                      key: `liq-${o.symbol}`,
                      label: o.symbol,
                      venue: 'liquid',
                      share: (o.size || 0) / total,
                    })),
                    ...polyOrders.map((o, idx) => ({
                      key: `poly-${idx}`,
                      label: 'PM',
                      venue: 'polymarket',
                      share: (o.amount_usd || 0) / total,
                    })),
                  ] : []
                  return hasAny ? (
                    <div className="batch-execute-row">
                      <div className="pre-exec-summary">
                        <div className="alloc-bar">
                          {segments.map((seg) => (
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
                      <button type="button" className="execute-btn" disabled={executing} onClick={() => openConfirm(i, liquidOrders, polyOrders)}>Execute batch</button>
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
            <div className="content">Thinking…</div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="input-row">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && send()}
          placeholder="Ask about markets or trades..."
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
