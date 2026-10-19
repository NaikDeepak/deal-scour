/* eslint-disable react-refresh/only-export-components */
import { useEffect, useState } from 'react'
import {
  PLATFORM_META,
  radarApi,
  type RadarChannelItem,
  type RadarKeywordItem,
  type RadarPostItem,
} from '../../lib/api'
import { formatINR } from '../../lib/money'
import { Card, ErrorNote, inputClass, SectionTitle } from '../../lib/ui'
import { isSafeExternalUrl, renderReasonLabel } from '../deals/DealsPage'

export function parseChannelInput(raw: string): string {
  const s = (raw || '').trim()
  if (!s) return ''
  try {
    if (s.startsWith('http://') || s.startsWith('https://')) {
      const parsed = new URL(s)
      if (parsed.hash) {
        return parsed.hash.replace(/^#+/, '').trim()
      }
      const path = parsed.pathname.replace(/^\/+|\/+$/g, '')
      if (path && parsed.hostname.toLowerCase().includes('t.me')) {
        const last = path.split('/').pop() || ''
        return last ? `@${last}` : ''
      }
    }
  } catch {
    // fallback to raw
  }
  return s.replace(/^#+/, '').trim()
}

export function formatVerdictBadge(verdict: string): { label: string; className: string } {
  switch (verdict) {
    case 'good':
      return { label: 'GOOD', className: 'bg-emerald-100 text-emerald-800' }
    case 'expired':
      return { label: 'Expired', className: 'bg-amber-100 text-amber-800' }
    case 'unsupported_link':
      return { label: 'Unsupported link', className: 'bg-slate-200 text-slate-700' }
    case 'not_relevant':
    default:
      return { label: 'Not relevant', className: 'bg-slate-100 text-slate-600' }
  }
}

export default function RadarPage() {
  const [channels, setChannels] = useState<RadarChannelItem[]>([])
  const [keywords, setKeywords] = useState<RadarKeywordItem[]>([])
  const [posts, setPosts] = useState<RadarPostItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [channelInput, setChannelInput] = useState('')
  const [channelName, setChannelName] = useState('')
  const [keywordInput, setKeywordInput] = useState('')

  const [extConnected, setExtConnected] = useState(false)
  const [connectingExt, setConnectingExt] = useState(false)
  const [testAlertStatus, setTestAlertStatus] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    Promise.all([radarApi.channels(), radarApi.keywords(), radarApi.posts()])
      .then(([chRes, kwRes, postRes]) => {
        if (!active) return
        setChannels(chRes.channels)
        setKeywords(kwRes.keywords)
        setPosts(postRes.posts)
        setLoading(false)
      })
      .catch((e) => {
        if (!active) return
        setError((e as Error).message)
        setLoading(false)
      })

    function onWindowMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || event.source !== window || !event.data) return
      if (event.data.type === 'DEALSCOUR_RADAR_TOKEN_SAVED') {
        setConnectingExt(false)
        if (event.data.ok) {
          setExtConnected(true)
        } else {
          setError(event.data.error || 'Could not connect to extension')
        }
      }
    }

    window.addEventListener('message', onWindowMessage)
    return () => {
      active = false
      window.removeEventListener('message', onWindowMessage)
    }
  }, [])

  async function handleConnectExtension() {
    setError(null)
    setConnectingExt(true)
    try {
      const res = await radarApi.createExtensionToken()
      window.postMessage(
        {
          type: 'DEALSCOUR_SET_RADAR_TOKEN',
          token: res.token,
          apiOrigin: window.location.origin,
        },
        window.location.origin,
      )
    } catch (e) {
      setConnectingExt(false)
      setError((e as Error).message)
    }
  }

  async function handleSendTestAlert() {
    setError(null)
    setTestAlertStatus('Sending…')
    try {
      const res = await radarApi.sendTestAlert()
      if (res.ok) {
        setTestAlertStatus(
          res.telegram_sent
            ? 'Test alert queued for browser & sent to Telegram!'
            : 'Test alert queued for browser (Telegram held or token not configured).',
        )
      } else {
        setTestAlertStatus('Daily alert cap reached or duplicate alert.')
      }
    } catch (e) {
      setTestAlertStatus(null)
      setError((e as Error).message)
    }
  }

  async function handleAddChannel(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    const peerId = parseChannelInput(channelInput)
    const name = channelName.trim()
    if (!peerId || !name) return
    try {
      const created = await radarApi.addChannel(peerId, name)
      setChannels((prev) => {
        const exists = prev.some((c) => c.id === created.id)
        return exists ? prev.map((c) => (c.id === created.id ? created : c)) : [...prev, created]
      })
      setChannelInput('')
      setChannelName('')
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function handleToggleChannel(ch: RadarChannelItem) {
    setError(null)
    try {
      const updated = await radarApi.toggleChannel(ch.id, !ch.enabled)
      setChannels((prev) => prev.map((c) => (c.id === updated.id ? updated : c)))
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function handleAddKeyword(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    const kw = keywordInput.trim().toLowerCase()
    if (!kw) return
    try {
      const created = await radarApi.addKeyword(kw)
      setKeywords((prev) => (prev.some((k) => k.id === created.id) ? prev : [...prev, created]))
      setKeywordInput('')
    } catch (err) {
      setError((err as Error).message)
    }
  }

  async function handleRemoveKeyword(id: number) {
    setError(null)
    try {
      await radarApi.deleteKeyword(id)
      setKeywords((prev) => prev.filter((k) => k.id !== id))
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <SectionTitle>Deal Radar (Telegram)</SectionTitle>
            <p className="mt-1 text-xs text-slate-500">
              Reads open Telegram deal channels you choose and alerts only on verified household deals.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {extConnected ? (
              <span className="rounded-lg bg-emerald-100 px-3 py-1.5 text-xs font-bold text-emerald-800">
                Extension connected ✓
              </span>
            ) : (
              <button
                type="button"
                disabled={connectingExt}
                onClick={handleConnectExtension}
                className="rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-bold text-white hover:bg-slate-800 disabled:opacity-40"
              >
                {connectingExt ? 'Connecting…' : 'Connect extension'}
              </button>
            )}
            <button
              type="button"
              onClick={handleSendTestAlert}
              className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-bold text-slate-700 hover:bg-slate-50"
            >
              Send test alert
            </button>
          </div>
        </div>
        {testAlertStatus && (
          <p className="mt-2 rounded-lg bg-slate-100 px-2.5 py-1.5 text-xs text-slate-700">
            {testAlertStatus}
          </p>
        )}
      </Card>

      <ErrorNote error={error} />

      <Card>
        <SectionTitle>Telegram Channels</SectionTitle>
        <form onSubmit={handleAddChannel} className="mt-2 flex flex-col gap-2 sm:flex-row">
          <input
            type="text"
            placeholder="Telegram Web URL or ID (e.g. #-1001191090845)"
            value={channelInput}
            onChange={(e) => setChannelInput(e.target.value)}
            className={inputClass}
          />
          <input
            type="text"
            placeholder="Channel name (e.g. Offer Box 2.0)"
            value={channelName}
            onChange={(e) => setChannelName(e.target.value)}
            className={inputClass}
          />
          <button
            type="submit"
            className="shrink-0 rounded-lg bg-orange-700 px-3 py-1.5 text-xs font-bold text-white hover:bg-orange-800"
          >
            Add channel
          </button>
        </form>

        {channels.length === 0 ? (
          <p className="mt-3 text-xs text-slate-500">No channels added yet.</p>
        ) : (
          <ul className="mt-3 divide-y divide-slate-100">
            {channels.map((ch) => (
              <li key={ch.id} className="flex items-center justify-between py-2 text-xs">
                <div>
                  <span className="font-bold text-slate-800">{ch.name}</span>{' '}
                  <span className="font-mono text-slate-500">({ch.peer_id})</span>
                </div>
                <button
                  type="button"
                  onClick={() => handleToggleChannel(ch)}
                  className={`rounded-full px-2.5 py-0.5 text-[11px] font-bold ${
                    ch.enabled ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-200 text-slate-600'
                  }`}
                >
                  {ch.enabled ? 'Enabled' : 'Paused'}
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card>
        <SectionTitle>Untracked Product Keywords</SectionTitle>
        <p className="mt-1 text-xs text-slate-500">
          Keywords (e.g. whey, peanut butter, almonds) to evaluate against your best family unit price.
        </p>
        <form onSubmit={handleAddKeyword} className="mt-2 flex gap-2">
          <input
            type="text"
            placeholder="Add keyword (e.g. whey)"
            value={keywordInput}
            onChange={(e) => setKeywordInput(e.target.value)}
            className={inputClass}
          />
          <button
            type="submit"
            className="shrink-0 rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-bold text-white hover:bg-slate-800"
          >
            Add
          </button>
        </form>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {keywords.map((kw) => (
            <span
              key={kw.id}
              className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-700"
            >
              {kw.keyword}
              <button
                type="button"
                aria-label={`Remove ${kw.keyword}`}
                onClick={() => handleRemoveKeyword(kw.id)}
                className="ml-0.5 text-slate-400 hover:text-slate-700"
              >
                ×
              </button>
            </span>
          ))}
        </div>
      </Card>

      <Card>
        <SectionTitle>Recent Verdicts (Last 50 Posts)</SectionTitle>
        {loading ? (
          <p className="py-4 text-center text-xs text-slate-400">Loading recent posts…</p>
        ) : posts.length === 0 ? (
          <p className="py-4 text-center text-xs text-slate-500">No Telegram posts ingested yet.</p>
        ) : (
          <ul className="mt-3 divide-y divide-slate-100">
            {posts.map((post) => {
              const vBadge = formatVerdictBadge(post.verdict)
              const displayPrice = post.live_paise ?? post.posted_paise
              return (
                <li key={post.id} className="py-2.5 text-xs">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-1.5 pb-1">
                        <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${vBadge.className}`}>
                          {vBadge.label}
                        </span>
                        {post.reasons.map((r) => {
                          const rBadge = renderReasonLabel(r)
                          return (
                            <span
                              key={r}
                              className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${rBadge.className}`}
                            >
                              {rBadge.label}
                            </span>
                          )
                        })}
                      </div>
                      <div className="font-semibold text-slate-900">
                        {post.title || post.text}
                      </div>
                      {post.title && (
                        <div className="truncate text-[11px] text-slate-500">{post.text}</div>
                      )}
                      {post.product_url && isSafeExternalUrl(post.product_url) && (
                        <a
                          href={post.product_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="mt-1 inline-block font-semibold text-slate-700 underline"
                        >
                          Open on {post.platform ? PLATFORM_META[post.platform]?.name || post.platform : 'Shop'} ↗
                        </a>
                      )}
                    </div>
                    {displayPrice != null && (
                      <div className="shrink-0 text-right font-black text-slate-900">
                        {formatINR(displayPrice)}
                      </div>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </Card>
    </div>
  )
}
