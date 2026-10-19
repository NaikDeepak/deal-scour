/* eslint-disable react-refresh/only-export-components */
import { useEffect, useState } from 'react'
import {
  catalog,
  PLATFORM_META,
  type Family,
  type Platform,
} from '../../lib/api'
import { paiseToRupeesInput, parseRupees } from '../../lib/money'
import { Card, ErrorNote, inputClass, SectionTitle } from '../../lib/ui'

const CATEGORIES = [
  'dairy',
  'staples',
  'breakfast',
  'protein',
  'beverages',
  'snacks',
  'dryfruits',
  'cleaning',
  'personal',
  'fitness',
  'bakery',
  'poultry',
]

export function parseBulkUrls(text: string): string[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .slice(0, 20)
}

export function sourceLabel(source?: string): { label: string; className: string } | null {
  if (!source) return null
  switch (source) {
    case 'page':
      return { label: 'from page', className: 'bg-emerald-100 text-emerald-800' }
    case 'rules':
      return { label: 'guessed', className: 'bg-sky-100 text-sky-800' }
    case 'gemini':
      return { label: 'AI', className: 'bg-purple-100 text-purple-800' }
    case 'slug':
      return { label: 'from link', className: 'bg-slate-100 text-slate-700' }
    default:
      return null
  }
}

function SourceBadge({ source }: { source?: string }) {
  const badge = sourceLabel(source)
  if (!badge) return null
  return (
    <span className={`ml-1.5 rounded px-1.5 py-0.5 text-[10px] font-bold ${badge.className}`}>
      {badge.label}
    </span>
  )
}

function slug(s: string): string {
  return s
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_|_$/g, '')
    .slice(0, 40)
}

interface SingleFormState {
  title: string
  brand: string
  pack: string
  category: string
  family: string
  newFamily: string
  price: string
  mrp: string
  member: string
  inStock: boolean
  sources: Record<string, string>
  canonicalUrl: string
  platform: Platform | null
}

export default function AddProduct({ onAdded }: { onAdded: () => void }) {
  const [mode, setMode] = useState<'single' | 'bulk'>('single')
  const [url, setUrl] = useState('')
  const [loading, setLoading] = useState(false)
  const [families, setFamilies] = useState<Family[]>([])
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)

  const [form, setForm] = useState<SingleFormState>({
    title: '',
    brand: '',
    pack: '',
    category: 'dairy',
    family: '',
    newFamily: '',
    price: '',
    mrp: '',
    member: '',
    inStock: true,
    sources: {},
    canonicalUrl: '',
    platform: null,
  })

  // Bulk state
  const [bulkText, setBulkText] = useState('')
  const [bulkLoading, setBulkLoading] = useState(false)
  const [bulkRows, setBulkRows] = useState<
    Array<{
      id: string
      url: string
      platform: Platform
      title: string
      brand: string
      pack: string
      category: string
      family: string
      price: string
      mrp: string
      inStock: boolean
      sources: Record<string, string>
      saved: boolean
      saving: boolean
      error: string | null
    }>
  >([])

  useEffect(() => {
    catalog.families().then(setFamilies).catch(() => setFamilies([]))
  }, [])

  async function fillFromLink() {
    if (!url.trim()) return
    setError(null)
    setDone(null)
    setLoading(true)
    try {
      const sug = await catalog.autofill(url.trim())
      setForm({
        title: sug.title,
        brand: sug.brand,
        pack: sug.pack_label,
        category: sug.category || 'dairy',
        family: sug.family_key,
        newFamily: sug.family_key,
        price: sug.listed_paise != null ? paiseToRupeesInput(sug.listed_paise) : '',
        mrp: sug.mrp_paise != null ? paiseToRupeesInput(sug.mrp_paise) : '',
        member: '',
        inStock: sug.in_stock != null ? sug.in_stock : true,
        sources: sug.sources,
        canonicalUrl: sug.url,
        platform: sug.platform,
      })
    } catch (e) {
      setError((e as Error).message.replace(/^\d+: /, ''))
    } finally {
      setLoading(false)
    }
  }

  async function saveSingle() {
    const targetUrl = form.canonicalUrl || url.trim()
    if (!targetUrl) return
    const listed = parseRupees(form.price)
    const mrp = form.mrp.trim() === '' ? listed : parseRupees(form.mrp)
    const member = form.member.trim() === '' ? null : parseRupees(form.member)
    const family = form.family === '__new' ? slug(form.newFamily) : form.family

    if (!form.title.trim() || !form.brand.trim() || !form.pack.trim() || !family) {
      setError('Fill in name, brand, pack size and family.')
      return
    }
    if (listed === null || mrp === null || (form.member.trim() !== '' && member === null)) {
      setError('Enter prices in rupees, e.g. 275 or 275.50.')
      return
    }

    try {
      setError(null)
      const created = await catalog.addListing({
        url: targetUrl,
        title: form.title.trim(),
        brand: form.brand.trim(),
        pack_label: form.pack.trim(),
        category: form.category,
        family_key: family,
        listed_paise: listed,
        mrp_paise: mrp,
        member_price_paise: member,
        in_stock: form.inStock,
      })
      setDone(`Added ${form.title.trim()} (${created.listing_id})`)
      setUrl('')
      setForm({
        title: '',
        brand: '',
        pack: '',
        category: 'dairy',
        family: '',
        newFamily: '',
        price: '',
        mrp: '',
        member: '',
        inStock: true,
        sources: {},
        canonicalUrl: '',
        platform: null,
      })
      catalog.families().then(setFamilies).catch(() => {})
      onAdded()
    } catch (e) {
      setError((e as Error).message.replace(/^\d+: /, ''))
    }
  }

  async function fillBulk() {
    const urls = parseBulkUrls(bulkText)
    if (urls.length === 0) {
      setError('Paste at least one product URL.')
      return
    }
    setError(null)
    setBulkLoading(true)
    try {
      const res = await catalog.bulkAutofill(urls)
      setBulkRows(
        res.results.map((r, idx) => {
          const s = r.suggestion
          if (!s) {
            return {
              id: `bulk-${idx}-err`,
              url: r.url,
              platform: 'amazon' as Platform,
              title: r.url,
              brand: '',
              pack: '',
              category: 'dairy',
              family: '',
              price: '',
              mrp: '',
              inStock: false,
              sources: {},
              saved: false,
              saving: false,
              error: r.error || 'Failed to parse',
            }
          }
          return {
            id: `bulk-${idx}-${s.sku}`,
            url: s.url,
            platform: s.platform,
            title: s.title,
            brand: s.brand,
            pack: s.pack_label,
            category: s.category || 'dairy',
            family: s.family_key,
            price: s.listed_paise != null ? paiseToRupeesInput(s.listed_paise) : '',
            mrp: s.mrp_paise != null ? paiseToRupeesInput(s.mrp_paise) : '',
            inStock: s.in_stock != null ? s.in_stock : true,
            sources: s.sources,
            saved: false,
            saving: false,
            error: null,
          }
        })
      )
    } catch (e) {
      setError((e as Error).message.replace(/^\d+: /, ''))
    } finally {
      setBulkLoading(false)
    }
  }

  async function saveBulkRow(idx: number) {
    const row = bulkRows[idx]
    if (!row || row.saved || row.saving) return
    const listed = parseRupees(row.price)
    const mrp = row.mrp.trim() === '' ? listed : parseRupees(row.mrp)
    if (listed === null || mrp === null) {
      setBulkRows((rows) =>
        rows.map((r, i) => (i === idx ? { ...r, error: 'Enter valid price in ₹' } : r))
      )
      return
    }

    setBulkRows((rows) =>
      rows.map((r, i) => (i === idx ? { ...r, saving: true, error: null } : r))
    )

    try {
      await catalog.addListing({
        url: row.url,
        title: row.title.trim(),
        brand: row.brand.trim(),
        pack_label: row.pack.trim(),
        category: row.category,
        family_key: row.family || 'staples',
        listed_paise: listed,
        mrp_paise: mrp,
        member_price_paise: null,
        in_stock: row.inStock,
      })
      setBulkRows((rows) =>
        rows.map((r, i) => (i === idx ? { ...r, saved: true, saving: false } : r))
      )
      onAdded()
    } catch (e) {
      setBulkRows((rows) =>
        rows.map((r, i) => (i === idx ? { ...r, saving: false, error: (e as Error).message } : r))
      )
    }
  }

  return (
    <Card>
      <div className="flex items-center justify-between">
        <SectionTitle>Add a product</SectionTitle>
        <div className="flex gap-1 rounded-lg bg-slate-100 p-0.5 text-xs font-semibold">
          <button
            type="button"
            onClick={() => setMode('single')}
            className={`rounded px-2.5 py-1 ${mode === 'single' ? 'bg-white shadow-xs text-slate-900' : 'text-slate-500'}`}
          >
            Single link
          </button>
          <button
            type="button"
            onClick={() => setMode('bulk')}
            className={`rounded px-2.5 py-1 ${mode === 'bulk' ? 'bg-white shadow-xs text-slate-900' : 'text-slate-500'}`}
          >
            Paste several
          </button>
        </div>
      </div>

      <ErrorNote error={error} />
      {done && <p className="mt-2 text-xs font-medium text-emerald-800">{done}</p>}

      {mode === 'single' ? (
        <div className="mt-3 space-y-3">
          <div className="flex gap-2">
            <input
              className={`${inputClass} flex-1`}
              placeholder="Paste product link (Amazon, Flipkart, Blinkit, Instamart, Zepto)…"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && fillFromLink()}
            />
            <button
              type="button"
              disabled={loading || !url.trim()}
              onClick={fillFromLink}
              className="rounded-xl bg-orange-700 px-3.5 py-2 text-xs font-bold text-white hover:bg-orange-800 disabled:opacity-40"
            >
              {loading ? 'Filling…' : 'Fill from link'}
            </button>
          </div>

          {(form.title || form.canonicalUrl) && (
            <div className="space-y-3 rounded-xl border border-slate-200 bg-slate-50/50 p-3">
              {form.platform && (
                <div className="flex items-center gap-1.5 text-xs text-slate-600">
                  <span
                    className="h-2 w-2 rounded-full"
                    style={{ backgroundColor: PLATFORM_META[form.platform].color }}
                  />
                  <span className="font-semibold text-slate-800">
                    {PLATFORM_META[form.platform].name}
                  </span>
                  <SourceBadge source={form.sources.title} />
                </div>
              )}

              <div className="space-y-1">
                <div className="flex items-center text-xs font-medium text-slate-600">
                  <span>Product name</span>
                  <SourceBadge source={form.sources.title} />
                </div>
                <input
                  className={inputClass}
                  value={form.title}
                  onChange={(e) => setForm({ ...form, title: e.target.value })}
                />
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1">
                  <div className="flex items-center text-xs font-medium text-slate-600">
                    <span>Brand</span>
                    <SourceBadge source={form.sources.brand} />
                  </div>
                  <input
                    className={inputClass}
                    value={form.brand}
                    onChange={(e) => setForm({ ...form, brand: e.target.value })}
                  />
                </div>
                <div className="space-y-1">
                  <div className="flex items-center text-xs font-medium text-slate-600">
                    <span>Pack size</span>
                    <SourceBadge source={form.sources.pack_label} />
                  </div>
                  <input
                    className={inputClass}
                    placeholder="e.g. 500g, 1L, 10pcs"
                    value={form.pack}
                    onChange={(e) => setForm({ ...form, pack: e.target.value })}
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1">
                  <div className="flex items-center text-xs font-medium text-slate-600">
                    <span>Category</span>
                    <SourceBadge source={form.sources.category} />
                  </div>
                  <select
                    className={inputClass}
                    value={form.category}
                    onChange={(e) => setForm({ ...form, category: e.target.value })}
                  >
                    {CATEGORIES.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="space-y-1">
                  <div className="flex items-center text-xs font-medium text-slate-600">
                    <span>Family</span>
                    <SourceBadge source={form.sources.family_key} />
                  </div>
                  <select
                    className={inputClass}
                    value={form.family}
                    onChange={(e) => setForm({ ...form, family: e.target.value })}
                  >
                    <option value="">Choose a family…</option>
                    {families.map((f) => (
                      <option key={f.family_key} value={f.family_key}>
                        {f.family_key}
                      </option>
                    ))}
                    <option value="__new">+ New family…</option>
                  </select>
                </div>
              </div>

              {form.family === '__new' && (
                <div className="space-y-1">
                  <span className="text-xs font-medium text-slate-600">New family name</span>
                  <input
                    className={inputClass}
                    placeholder="e.g. butter, paneer, oats"
                    value={form.newFamily}
                    onChange={(e) => setForm({ ...form, newFamily: e.target.value })}
                  />
                </div>
              )}

              <div className="grid grid-cols-3 gap-2">
                <div className="space-y-1">
                  <div className="flex items-center text-xs font-medium text-slate-600">
                    <span>Price (₹)</span>
                    <SourceBadge source={form.sources.listed_paise} />
                  </div>
                  <input
                    className={inputClass}
                    inputMode="decimal"
                    placeholder="e.g. 275"
                    value={form.price}
                    onChange={(e) => setForm({ ...form, price: e.target.value })}
                  />
                </div>
                <div className="space-y-1">
                  <div className="flex items-center text-xs font-medium text-slate-600">
                    <span>MRP (₹)</span>
                    <SourceBadge source={form.sources.mrp_paise} />
                  </div>
                  <input
                    className={inputClass}
                    inputMode="decimal"
                    placeholder="optional"
                    value={form.mrp}
                    onChange={(e) => setForm({ ...form, mrp: e.target.value })}
                  />
                </div>
                <div className="space-y-1">
                  <span className="text-xs font-medium text-slate-600">Member (₹)</span>
                  <input
                    className={inputClass}
                    inputMode="decimal"
                    placeholder="optional"
                    value={form.member}
                    onChange={(e) => setForm({ ...form, member: e.target.value })}
                  />
                </div>
              </div>

              <div className="flex items-center justify-between pt-2">
                <label className="flex items-center gap-2 text-xs font-medium text-slate-600">
                  <input
                    type="checkbox"
                    checked={form.inStock}
                    onChange={(e) => setForm({ ...form, inStock: e.target.checked })}
                  />
                  In stock
                </label>
                <button
                  type="button"
                  onClick={saveSingle}
                  className="rounded-xl bg-slate-900 px-4 py-2 text-xs font-bold text-white hover:bg-slate-800"
                >
                  Save product
                </button>
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="mt-3 space-y-3">
          <textarea
            className={`${inputClass} h-24 font-mono text-xs`}
            placeholder={`Paste up to 20 links, one per line:\nhttps://www.amazon.in/dp/B072HG4WNC\nhttps://blinkit.com/prn/amul-butter/prid/123`}
            value={bulkText}
            onChange={(e) => setBulkText(e.target.value)}
          />
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-500">
              {parseBulkUrls(bulkText).length} links ready (max 20)
            </span>
            <div className="flex items-center gap-2">
              <span className="text-[11px] text-slate-400">About 10 s per link</span>
              <button
                type="button"
                disabled={bulkLoading || parseBulkUrls(bulkText).length === 0}
                onClick={fillBulk}
                className="rounded-xl bg-orange-700 px-3.5 py-2 text-xs font-bold text-white hover:bg-orange-800 disabled:opacity-40"
              >
                {bulkLoading ? 'Filling links…' : 'Fill links'}
              </button>
            </div>
          </div>

          {bulkRows.length > 0 && (
            <div className="space-y-2 pt-2">
              <div className="text-xs font-bold text-slate-700">
                Confirm & save each product ({bulkRows.filter((r) => r.saved).length}/{bulkRows.length} saved):
              </div>
              <div className="space-y-2 max-h-96 overflow-y-auto">
                {bulkRows.map((row, idx) => (
                  <div
                    key={row.id}
                    className={`rounded-xl border p-2.5 text-xs ${row.saved ? 'border-emerald-200 bg-emerald-50/50' : 'border-slate-200 bg-white'}`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5 font-bold text-slate-800">
                          <span
                            className="h-2 w-2 rounded-full"
                            style={{ backgroundColor: PLATFORM_META[row.platform].color }}
                          />
                          <span className="truncate">{row.title}</span>
                        </div>
                        <div className="mt-1 flex flex-wrap gap-2 text-slate-500">
                          <span>
                            Brand: <strong>{row.brand}</strong>
                            <SourceBadge source={row.sources.brand} />
                          </span>
                          <span>
                            Pack: <strong>{row.pack}</strong>
                            <SourceBadge source={row.sources.pack_label} />
                          </span>
                          <span>
                            Family: <strong>{row.family || 'unassigned'}</strong>
                            <SourceBadge source={row.sources.family_key} />
                          </span>
                        </div>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <input
                          className="w-16 rounded border border-slate-200 px-1.5 py-1 text-right text-xs"
                          placeholder="Price ₹"
                          value={row.price}
                          disabled={row.saved}
                          onChange={(e) =>
                            setBulkRows((rows) =>
                              rows.map((r, i) => (i === idx ? { ...r, price: e.target.value } : r))
                            )
                          }
                        />
                        {row.saved ? (
                          <span className="rounded bg-emerald-100 px-2 py-1 text-xs font-bold text-emerald-800">
                            Saved ✓
                          </span>
                        ) : (
                          <button
                            type="button"
                            disabled={row.saving || !row.price}
                            onClick={() => saveBulkRow(idx)}
                            className="rounded bg-slate-900 px-2.5 py-1 text-xs font-bold text-white hover:bg-slate-800 disabled:opacity-40"
                          >
                            {row.saving ? '…' : 'Save'}
                          </button>
                        )}
                      </div>
                    </div>
                    {row.error && <p className="mt-1 text-rose-600">{row.error}</p>}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </Card>
  )
}
