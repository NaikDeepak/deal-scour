import { useEffect, useState } from 'react'
import { catalog, PLATFORM_META, type Family, type ProductRef } from '../../lib/api'
import { parseRupees } from '../../lib/money'
import { Card, ErrorNote, inputClass, SectionTitle } from '../../lib/ui'

const CATEGORIES = ['dairy', 'staples', 'breakfast', 'protein', 'beverages', 'snacks', 'dryfruits', 'cleaning', 'personal']

function slug(s: string): string {
  return s.toLowerCase().trim().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '').slice(0, 40)
}

export default function AddProduct({ onAdded }: { onAdded: () => void }) {
  const [url, setUrl] = useState('')
  const [ref, setRef] = useState<ProductRef | null>(null)
  const [families, setFamilies] = useState<Family[]>([])
  const [form, setForm] = useState({ title: '', brand: '', pack: '', category: 'dairy', family: '', newFamily: '', price: '', mrp: '', member: '' })
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)

  useEffect(() => {
    catalog.families().then(setFamilies).catch(() => setFamilies([]))
  }, [])

  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value })

  async function check() {
    setError(null)
    setDone(null)
    try {
      setRef(await catalog.parseLink(url.trim()))
    } catch (e) {
      setRef(null)
      setError((e as Error).message.replace(/^\d+: /, ''))
    }
  }

  async function save() {
    if (!ref) return
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
        url: ref.url,
        title: form.title.trim(),
        brand: form.brand.trim(),
        pack_label: form.pack.trim(),
        category: form.category,
        family_key: family,
        listed_paise: listed,
        mrp_paise: mrp,
        member_price_paise: member,
        in_stock: true,
      })
      setDone(`Added ${form.brand} ${form.pack} (${PLATFORM_META[ref.platform].name}). You can now add it to a list.`)
      setUrl('')
      setRef(null)
      setForm({ ...form, title: '', brand: '', pack: '', price: '', mrp: '', member: '', newFamily: '' })
      void created
      onAdded()
      catalog.families().then(setFamilies).catch(() => undefined)
    } catch (e) {
      setError((e as Error).message.replace(/^\d+: /, ''))
    }
  }

  return (
    <Card className="space-y-2">
      <SectionTitle>Add a product</SectionTitle>
      <p className="text-xs text-slate-500">
        Paste a product link from Amazon, Flipkart, Blinkit, Zepto or Instamart. Amazon and Flipkart prices can then refresh automatically.
      </p>
      <div className="flex gap-2">
        <input className={inputClass} inputMode="url" placeholder="https://www.amazon.in/…/dp/…" value={url} onChange={(e) => setUrl(e.target.value)} />
        <button type="button" onClick={check} disabled={!url.trim()} className="shrink-0 rounded-lg bg-slate-900 px-3 text-xs font-bold text-white disabled:opacity-40">
          Check
        </button>
      </div>
      {ref && (
        <div className="space-y-2 rounded-xl bg-slate-50 p-3">
          <p className="text-xs font-semibold">
            {PLATFORM_META[ref.platform].name} product <span className="font-mono text-slate-500">{ref.sku}</span>
          </p>
          <div className="grid grid-cols-2 gap-2">
            <label className="col-span-2 text-xs text-slate-500">
              Name
              <input className={inputClass} placeholder="Amul Pasteurised Butter" value={form.title} onChange={set('title')} />
            </label>
            <label className="text-xs text-slate-500">
              Brand
              <input className={inputClass} placeholder="Amul" value={form.brand} onChange={set('brand')} />
            </label>
            <label className="text-xs text-slate-500">
              Pack size
              <input className={inputClass} placeholder="500g, 1L, 6 pcs" value={form.pack} onChange={set('pack')} />
            </label>
            <label className="text-xs text-slate-500">
              Category
              <select className={inputClass} value={form.category} onChange={set('category')}>
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs text-slate-500">
              Family (what it can replace)
              <select className={inputClass} value={form.family} onChange={set('family')}>
                <option value="">Choose…</option>
                {families.map((f) => (
                  <option key={f.family_key} value={f.family_key}>
                    {f.family_key.replace(/_/g, ' ')}
                  </option>
                ))}
                <option value="__new">+ New family…</option>
              </select>
            </label>
            {form.family === '__new' && (
              <label className="col-span-2 text-xs text-slate-500">
                New family name
                <input className={inputClass} placeholder="e.g. butter, cheese slices, eggs, whey protein" value={form.newFamily} onChange={set('newFamily')} />
              </label>
            )}
            <label className="text-xs text-slate-500">
              Price you see (₹)
              <input className={inputClass} inputMode="decimal" value={form.price} onChange={set('price')} />
            </label>
            <label className="text-xs text-slate-500">
              MRP (₹, optional)
              <input className={inputClass} inputMode="decimal" value={form.mrp} onChange={set('mrp')} />
            </label>
            <label className="col-span-2 text-xs text-slate-500">
              {PLATFORM_META[ref.platform].membership} price (₹, optional)
              <input className={inputClass} inputMode="decimal" value={form.member} onChange={set('member')} />
            </label>
          </div>
          <button type="button" onClick={save} className="w-full rounded-lg bg-orange-600 py-2 text-xs font-bold text-white">
            Add product
          </button>
        </div>
      )}
      <ErrorNote error={error} />
      {done && <p className="rounded-xl bg-emerald-50 p-2 text-xs text-emerald-800">{done}</p>}
    </Card>
  )
}
