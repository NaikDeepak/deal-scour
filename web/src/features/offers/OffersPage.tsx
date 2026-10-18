import { useCallback, useEffect, useState } from 'react'
import { api, PLATFORM_META, PLATFORMS, type Platform, type SavedOffer } from '../../lib/api'
import { formatINR, parseRupees } from '../../lib/money'
import { Card, ErrorNote, inputClass, SectionTitle } from '../../lib/ui'

type Template = 'flat' | 'pct_cap'

function describeOffer(o: Pick<SavedOffer, 'kind' | 'value_paise' | 'min_order_paise' | 'rate_bp' | 'cap_paise'>): string {
  if (o.kind === 'flat') return `${formatINR(o.value_paise)} back on ${formatINR(o.min_order_paise)}+`
  if (o.kind === 'pct_cap') return `${o.rate_bp / 100}% up to ${formatINR(o.cap_paise ?? 0)} on ${formatINR(o.min_order_paise)}+`
  return 'Tiered offer'
}

export default function OffersPage() {
  const [offers, setOffers] = useState<SavedOffer[]>([])
  const [error, setError] = useState<string | null>(null)
  const [platform, setPlatform] = useState<Platform>('amazon')
  const [template, setTemplate] = useState<Template>('flat')
  const [minOrder, setMinOrder] = useState('500')
  const [value, setValue] = useState('50')
  const [rate, setRate] = useState('10')
  const [uses, setUses] = useState('2')
  const [validTo, setValidTo] = useState('')
  const [note, setNote] = useState('')

  const load = useCallback(() => {
    api.offers().then(setOffers).catch((e: Error) => setError(e.message))
  }, [])
  useEffect(load, [load])

  async function add() {
    const min = parseRupees(minOrder)
    const val = parseRupees(value)
    const usesN = Number(uses)
    const rateN = Number(rate)
    if (min === null || val === null || !Number.isInteger(usesN) || usesN < 1) {
      setError('Enter amounts in rupees and at least 1 use.')
      return
    }
    if (template === 'pct_cap' && !(rateN > 0 && rateN <= 100)) {
      setError('Percent must be between 1 and 100.')
      return
    }
    const prefix = PLATFORM_META[platform].name.slice(0, 2).toUpperCase()
    const code = `${prefix}${Date.now().toString(36).slice(-4).toUpperCase()}`
    try {
      setError(null)
      await api.createOffer({
        code,
        platform,
        kind: template,
        min_order_paise: min,
        value_paise: template === 'flat' ? val : 0,
        rate_bp: template === 'pct_cap' ? Math.round(rateN * 100) : 0,
        cap_paise: template === 'pct_cap' ? val : null,
        tiers: [],
        uses_left: usesN,
        stack_group: template === 'pct_cap' ? 'bank' : 'platform_coupon',
        value_type: platform === 'amazon' ? 'amazon_pay' : 'cash',
        multiplier_bp: null,
        eligible_categories: null,
        valid_to: validTo || null,
        note: note || null,
      })
      setNote('')
      load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  async function archive(id: number) {
    try {
      await api.archiveOffer(id)
      load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <SectionTitle>Add an offer you hold</SectionTitle>
        <p className="mt-1 text-xs text-slate-500">Seen in an app, SMS or email. Plans use it until its uses run out or it expires.</p>
        <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
          <label className="text-xs text-slate-500">
            Platform
            <select className={inputClass} value={platform} onChange={(e) => setPlatform(e.target.value as Platform)}>
              {PLATFORMS.map((p) => (
                <option key={p} value={p}>
                  {PLATFORM_META[p].name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-slate-500">
            Type
            <select className={inputClass} value={template} onChange={(e) => setTemplate(e.target.value as Template)}>
              <option value="flat">₹ off on min order</option>
              <option value="pct_cap">% off up to a cap (bank)</option>
            </select>
          </label>
          <label className="text-xs text-slate-500">
            Min order (₹)
            <input className={inputClass} inputMode="decimal" value={minOrder} onChange={(e) => setMinOrder(e.target.value)} />
          </label>
          {template === 'pct_cap' && (
            <label className="text-xs text-slate-500">
              Percent
              <input className={inputClass} inputMode="decimal" value={rate} onChange={(e) => setRate(e.target.value)} />
            </label>
          )}
          <label className="text-xs text-slate-500">
            {template === 'flat' ? 'Cashback (₹)' : 'Cap (₹)'}
            <input className={inputClass} inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} />
          </label>
          <label className="text-xs text-slate-500">
            Uses left
            <input className={inputClass} inputMode="numeric" value={uses} onChange={(e) => setUses(e.target.value)} />
          </label>
          <label className="text-xs text-slate-500">
            Valid until
            <input className={inputClass} type="date" value={validTo} onChange={(e) => setValidTo(e.target.value)} />
          </label>
          <label className="col-span-2 text-xs text-slate-500">
            Note
            <input className={inputClass} maxLength={200} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. from the app banner" />
          </label>
        </div>
        <button type="button" onClick={add} className="mt-3 rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-bold text-white">
          Save offer
        </button>
      </Card>

      <ErrorNote error={error} />

      <Card>
        <SectionTitle>Your offers</SectionTitle>
        {offers.length === 0 ? (
          <p className="mt-2 text-sm text-slate-500">No offers saved yet.</p>
        ) : (
          <ul className="mt-2 space-y-2">
            {offers.map((o) => (
              <li key={o.id} className="flex items-start justify-between gap-2 rounded-lg bg-amber-50 px-3 py-2 text-sm">
                <span>
                  <strong>{PLATFORM_META[o.platform].name}</strong> {describeOffer(o)}
                  <span className="block text-xs text-slate-600">
                    {o.uses_left} use{o.uses_left === 1 ? '' : 's'} left
                    {o.valid_to ? ` · until ${o.valid_to}` : ''}
                    {o.note ? ` · ${o.note}` : ''} · code {o.code}
                  </span>
                </span>
                <button type="button" onClick={() => archive(o.id)} className="shrink-0 text-xs font-semibold text-rose-600">
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}
