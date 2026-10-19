import { useMemo, useState } from 'react'
import { api, PLATFORM_META, type Deal, type Platform } from '../../lib/api'
import { formatINR, paiseToRupeesInput, parseRupees } from '../../lib/money'
import { usePreference } from '../../lib/preference'
import { useProducts } from '../../lib/products'
import { isProductPage } from '../../lib/links'
import { Card, ErrorNote, inputClass, SectionTitle } from '../../lib/ui'
import AddProduct from './AddProduct'
import FetcherStatus from './FetcherStatus'
import PriceHistory from './PriceHistory'

const FRESHNESS: Record<Deal['freshness'], { label: string; className: string }> = {
  fresh: { label: 'Fresh', className: 'bg-emerald-100 text-emerald-800' },
  ok: { label: 'Recent', className: 'bg-sky-100 text-sky-800' },
  stale: { label: 'Stale: check it', className: 'bg-amber-100 text-amber-800' },
  sample: { label: 'Sample price', className: 'bg-slate-100 text-slate-600' },
}

function age(iso: string | null): string {
  if (!iso) return ''
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000))
  if (mins < 60) return `${mins} min ago`
  if (mins < 48 * 60) return `${Math.round(mins / 60)} h ago`
  return `${Math.round(mins / 1440)} days ago`
}

export default function PricesPage() {
  const [members] = usePreference<Platform[]>('members', ['amazon', 'instamart', 'flipkart'])
  const [reload, setReload] = useState(0)
  const { deals } = useProducts(members, reload)
  const [query, setQuery] = useState('')
  const [editing, setEditing] = useState<string | null>(null)
  const [showHistory, setShowHistory] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    return deals
      .filter((d) => !q || `${d.brand} ${d.title} ${d.pack_label}`.toLowerCase().includes(q))
      .sort((a, b) => a.brand.localeCompare(b.brand) || a.pack_label.localeCompare(b.pack_label) || a.platform.localeCompare(b.platform))
  }, [deals, query])

  return (
    <div className="space-y-4">
      <AddProduct onAdded={() => setReload((n) => n + 1)} />
      <FetcherStatus onRefreshed={() => setReload((n) => n + 1)} />
      <Card>
        <SectionTitle>Prices you've seen</SectionTitle>
        <p className="mt-1 text-xs text-slate-500">
          Saw a price in an app? Record it here. Plans use the newest price and show how old it is.
        </p>
        <input className={`${inputClass} mt-2`} placeholder="Search items…" value={query} onChange={(e) => setQuery(e.target.value)} />
      </Card>
      <ErrorNote error={error} />
      <ul className="space-y-2">
        {shown.map((d) => (
          <li key={d.id} className="rounded-2xl border border-slate-200 bg-white p-3 shadow-sm">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="truncate text-sm font-bold">
                  {d.icon} {d.brand} {d.pack_label}
                </div>
                <div className="truncate text-xs text-slate-500">{d.title}</div>
                <div className="flex flex-wrap items-center gap-1.5 text-xs text-slate-600">
                  <span className="h-2 w-2 rounded-full" style={{ backgroundColor: PLATFORM_META[d.platform].color }} />
                  <a
                    href={d.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-semibold text-slate-800 underline decoration-slate-300 underline-offset-2 hover:decoration-slate-800"
                  >
                    {isProductPage(d.url) ? 'Open on' : 'Search on'} {PLATFORM_META[d.platform].name} ↗
                  </a>
                  <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${FRESHNESS[d.freshness].className}`}>
                    {FRESHNESS[d.freshness].label}
                  </span>
                  {d.observed_at && <span>{age(d.observed_at)}</span>}
                  {!d.in_stock && <span className="rounded bg-rose-100 px-1.5 py-0.5 text-[10px] font-bold text-rose-700">Out of stock</span>}
                </div>
              </div>
              <div className="shrink-0 text-right">
                <div className="text-sm font-black">{formatINR(d.unit_price_paise)}</div>
                <div className="mt-1 flex items-center justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setShowHistory(showHistory === d.id ? null : d.id)}
                    className="text-xs font-semibold text-slate-600 hover:text-slate-900"
                  >
                    {showHistory === d.id ? 'Hide' : 'History'}
                  </button>
                  <button
                    type="button"
                    onClick={() => setEditing(editing === d.id ? null : d.id)}
                    className="text-xs font-semibold text-orange-700"
                  >
                    {editing === d.id ? 'Cancel' : 'Update'}
                  </button>
                </div>
              </div>
            </div>
            {showHistory === d.id && (
              <PriceHistory listingId={d.id} onTargetUpdated={() => setReload((n) => n + 1)} />
            )}
            {editing === d.id && (
              <PriceForm
                deal={d}
                onSaved={() => {
                  setEditing(null)
                  setReload((n) => n + 1)
                }}
                onError={setError}
              />
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

function PriceForm({ deal, onSaved, onError }: { deal: Deal; onSaved: () => void; onError: (e: string | null) => void }) {
  const [listed, setListed] = useState('')
  const [mrp, setMrp] = useState(paiseToRupeesInput(deal.mrp_paise))
  const [member, setMember] = useState('')
  const [inStock, setInStock] = useState(true)

  async function save() {
    const l = parseRupees(listed)
    const m = parseRupees(mrp)
    const mem = member.trim() === '' ? null : parseRupees(member)
    if (l === null || l <= 0 || m === null || (member.trim() !== '' && mem === null)) {
      onError('Enter prices in rupees, e.g. 649 or 649.50.')
      return
    }
    try {
      onError(null)
      await api.observePrice({ listing_id: deal.id, listed_paise: l, mrp_paise: m, member_price_paise: mem, in_stock: inStock, eta_minutes: null, note: null })
      onSaved()
    } catch (e) {
      onError((e as Error).message)
    }
  }

  return (
    <div className="mt-3 grid grid-cols-3 gap-2 border-t border-slate-100 pt-3">
      <label className="text-xs text-slate-500">
        Price (₹)
        <input className={inputClass} inputMode="decimal" value={listed} onChange={(e) => setListed(e.target.value)} autoFocus />
      </label>
      <label className="text-xs text-slate-500">
        MRP (₹)
        <input className={inputClass} inputMode="decimal" value={mrp} onChange={(e) => setMrp(e.target.value)} />
      </label>
      <label className="text-xs text-slate-500">
        {PLATFORM_META[deal.platform].membership} price
        <input className={inputClass} inputMode="decimal" placeholder="optional" value={member} onChange={(e) => setMember(e.target.value)} />
      </label>
      <label className="col-span-2 flex items-center gap-2 text-xs text-slate-600">
        <input type="checkbox" checked={inStock} onChange={(e) => setInStock(e.target.checked)} /> In stock
      </label>
      <button type="button" onClick={save} className="rounded-lg bg-slate-900 py-1.5 text-xs font-bold text-white">
        Save
      </button>
    </div>
  )
}
