/* eslint-disable react-refresh/only-export-components */
import { useEffect, useState } from 'react'
import { catalog, type ListingHistory } from '../../lib/api'
import { formatINR, paiseToRupeesInput, parseRupees } from '../../lib/money'
import { inputClass } from '../../lib/ui'

export function buildSparklinePoints(
  prices: number[],
  width: number = 140,
  height: number = 32,
  padding: number = 4
): string {
  if (prices.length < 2) return ''
  const min = Math.min(...prices)
  const max = Math.max(...prices)
  const range = max - min || 1

  const usableW = width - padding * 2
  const usableH = height - padding * 2

  return prices
    .map((p, idx) => {
      const x = padding + (idx / (prices.length - 1)) * usableW
      // Invert Y so higher price is higher up
      const y = height - padding - ((p - min) / range) * usableH
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
}

export default function PriceHistory({
  listingId,
  onTargetUpdated,
}: {
  listingId: string
  onTargetUpdated?: () => void
}) {
  const [history, setHistory] = useState<ListingHistory | null>(null)
  const [loading, setLoading] = useState(true)
  const [targetInput, setTargetInput] = useState('')
  const [savingTarget, setSavingTarget] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    setLoading(true)
    catalog
      .history(listingId, 90)
      .then((h) => {
        if (!active) return
        setHistory(h)
        setTargetInput(h.target_paise != null ? paiseToRupeesInput(h.target_paise) : '')
        setLoading(false)
      })
      .catch((e) => {
        if (!active) return
        setError((e as Error).message)
        setLoading(false)
      })
    return () => {
      active = false
    }
  }, [listingId])

  async function saveTarget() {
    if (!targetInput.trim()) {
      clearTarget()
      return
    }
    const paise = parseRupees(targetInput)
    if (paise === null || paise <= 0) {
      setError('Enter a valid target in rupees, e.g. 240')
      return
    }
    setError(null)
    setSavingTarget(true)
    try {
      await catalog.setWatch(listingId, paise)
      setHistory((prev) => (prev ? { ...prev, target_paise: paise } : prev))
      onTargetUpdated?.()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSavingTarget(false)
    }
  }

  async function clearTarget() {
    setError(null)
    setSavingTarget(true)
    try {
      await catalog.deleteWatch(listingId)
      setTargetInput('')
      setHistory((prev) => (prev ? { ...prev, target_paise: null } : prev))
      onTargetUpdated?.()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSavingTarget(false)
    }
  }

  if (loading) {
    return <div className="text-xs text-slate-400 py-1">Loading price history…</div>
  }

  if (!history) {
    return null
  }

  // Chronological order for sparkline (observations returned newest-first from API)
  const chronological = [...history.observations].reverse()
  const prices = chronological.map((o) => o.listed_paise)
  const sparkPoints = buildSparklinePoints(prices)

  return (
    <div className="mt-2.5 rounded-xl border border-slate-100 bg-slate-50/70 p-2.5 text-xs text-slate-700">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <span className="font-semibold text-slate-800">90-day History</span>
          <div className="mt-0.5 flex flex-wrap gap-2 text-[11px] text-slate-500">
            {history.low_30d != null && (
              <span>
                30-day low: <strong className="text-emerald-700">{formatINR(history.low_30d)}</strong>
              </span>
            )}
            {history.avg_30d != null && (
              <span>
                30-day avg: <strong>{formatINR(history.avg_30d)}</strong>
              </span>
            )}
            {history.high_30d != null && (
              <span>
                High: <strong>{formatINR(history.high_30d)}</strong>
              </span>
            )}
          </div>
        </div>

        {prices.length >= 2 ? (
          <div className="flex items-center gap-1">
            <svg
              className="h-8 w-36 overflow-visible"
              viewBox="0 0 140 32"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
              aria-label="Price history sparkline"
            >
              <polyline
                fill="none"
                stroke="#c2410c"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                points={sparkPoints}
              />
            </svg>
          </div>
        ) : (
          <span className="text-[11px] text-slate-400">1 observation</span>
        )}
      </div>

      <div className="mt-2.5 flex items-center gap-2 border-t border-slate-200/60 pt-2">
        <label className="flex items-center gap-1.5 text-[11px] font-medium text-slate-600">
          <span>Tell me below ₹</span>
          <input
            className={`${inputClass} w-20 py-1 text-right text-xs`}
            placeholder="e.g. 240"
            inputMode="decimal"
            value={targetInput}
            onChange={(e) => setTargetInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && saveTarget()}
          />
        </label>
        <button
          type="button"
          disabled={savingTarget}
          onClick={saveTarget}
          className="rounded-lg bg-slate-900 px-2.5 py-1 text-[11px] font-bold text-white hover:bg-slate-800 disabled:opacity-40"
        >
          {savingTarget ? '…' : history.target_paise != null ? 'Update target' : 'Set target'}
        </button>
        {history.target_paise != null && (
          <button
            type="button"
            disabled={savingTarget}
            onClick={clearTarget}
            className="text-[11px] font-semibold text-rose-600 hover:text-rose-700"
          >
            Clear
          </button>
        )}
      </div>
      {error && <p className="mt-1 text-[11px] text-rose-600">{error}</p>}
    </div>
  )
}
