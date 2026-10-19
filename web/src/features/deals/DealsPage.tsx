/* eslint-disable react-refresh/only-export-components */
import { useEffect, useState } from 'react'
import {
  api,
  dealsApi,
  PLATFORM_META,
  radarApi,
  type DealFeedItem,
  type ListSummary,
  type RadarPostItem,
} from '../../lib/api'
import { isProductPage } from '../../lib/links'
import { formatINR } from '../../lib/money'
import { Card, ErrorNote, SectionTitle } from '../../lib/ui'

export function isSafeExternalUrl(url: string | null | undefined): url is string {
  if (!url) return false
  try {
    return new URL(url).protocol === 'https:'
  } catch {
    return false
  }
}

export function renderReasonLabel(
  reason: string,
  savingPct?: number
): { label: string; className: string } {
  switch (reason) {
    case 'below_target':
      return { label: '🎯 Below target', className: 'bg-emerald-100 text-emerald-800' }
    case 'low_30d':
    case '30d_low':
      return { label: '📉 30-day low', className: 'bg-sky-100 text-sky-800' }
    case 'under_avg':
      return {
        label: `⚡ ${savingPct ? `${savingPct}%` : '≥15%'} under avg`,
        className: 'bg-amber-100 text-amber-800',
      }
    case 'beats_family_best':
      return { label: '🏆 Beats family best', className: 'bg-emerald-100 text-emerald-800' }
    default:
      return { label: reason, className: 'bg-slate-100 text-slate-700' }
  }
}

export default function DealsPage() {
  const [deals, setDeals] = useState<DealFeedItem[]>([])
  const [telegramDeals, setTelegramDeals] = useState<RadarPostItem[]>([])
  const [lists, setLists] = useState<ListSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [addingId, setAddingId] = useState<string | null>(null)
  const [addedMap, setAddedMap] = useState<Record<string, string>>({})

  useEffect(() => {
    let active = true
    setLoading(true)
    Promise.all([
      dealsApi.feed(),
      api.lists(),
      radarApi.posts('good').catch(() => ({ posts: [] as RadarPostItem[] })),
    ])
      .then(([feedRes, listsRes, tgRes]) => {
        if (!active) return
        setDeals(feedRes.deals)
        setLists(listsRes.filter((l) => !l.archived))
        setTelegramDeals(tgRes.posts)
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
  }, [])

  async function handleAddToList(deal: DealFeedItem) {
    setError(null)
    setAddingId(deal.listing_id)
    try {
      let targetListId: number
      let listName = ''

      if (lists.length > 0) {
        targetListId = lists[0].id
        listName = lists[0].name
      } else {
        const created = await api.createList('My List', 'quick')
        targetListId = created.id
        listName = created.name
        setLists([created])
      }

      const lineId = `need-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`
      await api.addNeed(targetListId, {
        line_id: lineId,
        product_key: null,
        family_key: deal.family_key,
        qty: 1,
        quantity: deal.pack_label,
        need_by_minutes: null,
        lock_platform: null,
      })

      setAddedMap((prev) => ({ ...prev, [deal.listing_id]: listName }))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setAddingId(null)
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <SectionTitle>Staple Deals Feed</SectionTitle>
        <p className="mt-1 text-xs text-slate-500">
          Products you track that are below your target price, at their 30-day low, or deeply
          discounted vs average.
        </p>
      </Card>

      <ErrorNote error={error} />

      {loading ? (
        <div className="py-8 text-center text-xs text-slate-400">Loading deals feed…</div>
      ) : deals.length === 0 ? (
        <Card>
          <div className="py-8 text-center">
            <p className="text-sm font-semibold text-slate-700">No active deal alerts right now</p>
            <p className="mt-1 text-xs text-slate-500">
              Add products or set target prices on the <strong>Prices</strong> tab to get alerted
              when prices drop!
            </p>
          </div>
        </Card>
      ) : (
        <ul className="space-y-2.5">
          {deals.map((deal) => {
            const addedToList = addedMap[deal.listing_id]
            const isAdding = addingId === deal.listing_id

            return (
              <li
                key={deal.listing_id}
                className="rounded-2xl border border-slate-200 bg-white p-3.5 shadow-xs"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5 pb-1">
                      {deal.reasons.map((r) => {
                        const badge = renderReasonLabel(r, deal.saving_pct)
                        return (
                          <span
                            key={r}
                            className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${badge.className}`}
                          >
                            {badge.label}
                          </span>
                        )
                      })}
                      {deal.saving_pct > 0 && (
                        <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-bold text-emerald-700">
                          {deal.saving_pct}% off
                        </span>
                      )}
                    </div>

                    <div className="truncate text-sm font-bold text-slate-900">
                      {deal.icon} {deal.brand} {deal.pack_label}
                    </div>
                    <div className="truncate text-xs text-slate-500">{deal.title}</div>

                    <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-slate-600">
                      <span
                        className="h-2 w-2 rounded-full"
                        style={{ backgroundColor: PLATFORM_META[deal.platform].color }}
                      />
                      <a
                        href={deal.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="font-semibold text-slate-800 underline decoration-slate-300 underline-offset-2 hover:decoration-slate-800"
                      >
                        {isProductPage(deal.url) ? 'Open on' : 'Search on'}{' '}
                        {PLATFORM_META[deal.platform].name} ↗
                      </a>
                    </div>
                  </div>

                  <div className="shrink-0 text-right">
                    <div className="text-base font-black text-slate-900">
                      {formatINR(deal.listed_paise)}
                    </div>
                    <div className="text-[11px] text-slate-500">
                      {deal.avg_30d_paise ? (
                        <span>vs avg {formatINR(deal.avg_30d_paise)}</span>
                      ) : deal.mrp_paise > deal.listed_paise ? (
                        <span className="line-through">{formatINR(deal.mrp_paise)}</span>
                      ) : null}
                    </div>

                    <div className="mt-2">
                      {addedToList ? (
                        <span className="rounded-lg bg-emerald-100 px-2.5 py-1 text-xs font-bold text-emerald-800">
                          Added to {addedToList} ✓
                        </span>
                      ) : (
                        <button
                          type="button"
                          disabled={isAdding}
                          onClick={() => handleAddToList(deal)}
                          className="rounded-lg bg-orange-700 px-3 py-1.5 text-xs font-bold text-white hover:bg-orange-800 disabled:opacity-40"
                        >
                          {isAdding ? 'Adding…' : 'Add to list'}
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              </li>
            )
          })}
        </ul>
      )}

      <Card>
        <SectionTitle>From Telegram</SectionTitle>
        <p className="mt-1 text-xs text-slate-500">
          Verified GOOD deals spotted in your Telegram deal channels.
        </p>
        {telegramDeals.length === 0 ? (
          <p className="mt-3 text-xs text-slate-400">
            No Telegram deals right now. Configure channels on the <strong>Radar</strong> tab.
          </p>
        ) : (
          <ul className="mt-3 space-y-2">
            {telegramDeals.map((post) => {
              const price = post.live_paise ?? post.posted_paise
              return (
                <li
                  key={post.id}
                  className="flex items-start justify-between gap-3 rounded-xl border border-slate-100 bg-slate-50 p-3"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1 pb-1">
                      {post.reasons.map((r) => {
                        const badge = renderReasonLabel(r)
                        return (
                          <span
                            key={r}
                            className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${badge.className}`}
                          >
                            {badge.label}
                          </span>
                        )
                      })}
                    </div>
                    <div className="truncate text-sm font-bold text-slate-900">
                      {post.title || post.text}
                    </div>
                    {post.product_url && isSafeExternalUrl(post.product_url) && (
                      <a
                        href={post.product_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="mt-1 inline-block text-xs font-semibold text-slate-800 underline"
                      >
                        Open on{' '}
                        {post.platform ? PLATFORM_META[post.platform]?.name || post.platform : 'Shop'} ↗
                      </a>
                    )}
                  </div>
                  {price != null && (
                    <div className="shrink-0 text-right text-base font-black text-slate-900">
                      {formatINR(price)}
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </Card>
    </div>
  )
}
