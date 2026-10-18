import { useEffect, useMemo, useState } from 'react'
import {
  fetchDeals,
  PLATFORM_META,
  PLATFORMS,
  requestPlans,
  type Deal,
  type FillerIn,
  type LabelledPlanOut,
  type NeedIn,
  type OfferIn,
  type OrderOut,
  type Platform,
  type PlanSetOut,
} from '../../lib/api'
import { formatINR, parseRupees } from '../../lib/money'

const PLAN_LABELS: Record<LabelledPlanOut['label'], { title: string; blurb: string }> = {
  cheapest_now: { title: 'Cheapest now', blurb: 'Everything ordered today' },
  max_savings: { title: 'Max savings', blurb: 'Holds one basket until you top it up' },
  fastest: { title: 'Fastest', blurb: 'Quickest delivery for every item' },
}

interface Product {
  key: string
  title: string
  brand: string
  pack: string
  icon: string
  best: Deal
}

type OfferTemplate = 'flat' | 'pct_cap'

export default function PlansPage() {
  const [members, setMembers] = useState<Platform[]>(['amazon', 'instamart', 'flipkart'])
  const [deals, setDeals] = useState<Deal[]>([])
  const [needs, setNeeds] = useState<NeedIn[]>([])
  const [fillers, setFillers] = useState<string[]>([]) // product keys you'd buy anyway
  const [offers, setOffers] = useState<OfferIn[]>([])
  const [result, setResult] = useState<PlanSetOut | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    fetchDeals(members)
      .then((r) => setDeals(r.deals))
      .catch((e: Error) => setError(e.message))
  }, [members])

  const products = useMemo(() => {
    const byKey = new Map<string, Product>()
    for (const d of deals) {
      const p = byKey.get(d.product_key)
      if (!p || d.unit_price_paise < p.best.unit_price_paise) {
        byKey.set(d.product_key, { key: d.product_key, title: d.title, brand: d.brand, pack: d.pack_label, icon: d.icon, best: d })
      }
    }
    return [...byKey.values()].sort((a, b) => a.brand.localeCompare(b.brand))
  }, [deals])

  const productByKey = useMemo(() => new Map(products.map((p) => [p.key, p])), [products])

  function toggleMember(p: Platform) {
    setMembers((m) => (m.includes(p) ? m.filter((x) => x !== p) : [...m, p]))
    setResult(null)
  }

  function addNeed(key: string) {
    if (!key || needs.some((n) => n.product_key === key)) return
    setNeeds([...needs, { line_id: key, product_key: key, qty: 1, need_by_minutes: null, lock_platform: null }])
    setResult(null)
  }

  async function plan() {
    setLoading(true)
    setError(null)
    try {
      const fillerListings: FillerIn[] = deals
        .filter((d) => fillers.includes(d.product_key) && !needs.some((n) => n.product_key === d.product_key))
        .map((d) => ({ filler_id: `${d.product_key}@${d.platform}`, listing_id: d.id, score: 3 }))
      setResult(await requestPlans({ members, needs, offers, fillers: fillerListings }))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-5">
      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <h2 className="text-sm font-bold uppercase tracking-wide text-slate-500">Memberships</h2>
        <div className="mt-2 flex flex-wrap gap-2">
          {PLATFORMS.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => toggleMember(p)}
              className={`rounded-full border px-3 py-1 text-xs font-semibold ${
                members.includes(p)
                  ? 'border-emerald-500 bg-emerald-50 text-emerald-800'
                  : 'border-slate-200 bg-slate-50 text-slate-500'
              }`}
            >
              {PLATFORM_META[p].membership} {members.includes(p) ? 'on' : 'off'}
            </button>
          ))}
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <h2 className="text-sm font-bold uppercase tracking-wide text-slate-500">Your list</h2>
        <ProductPicker products={products} onPick={addNeed} placeholder="Add an item…" />
        {needs.length === 0 ? (
          <p className="mt-3 text-sm text-slate-500">Add what you need. Mark items "no rush" so they can wait for a better basket.</p>
        ) : (
          <ul className="mt-3 divide-y divide-slate-100">
            {needs.map((n) => {
              const p = productByKey.get(n.product_key)
              return (
                <li key={n.line_id} className="flex items-center gap-2 py-2 text-sm">
                  <span className="text-lg">{p?.icon}</span>
                  <span className="min-w-0 flex-1 truncate">
                    <span className="font-semibold">{p?.brand}</span> {p?.pack}
                  </span>
                  <select
                    aria-label="When do you need it"
                    value={n.need_by_minutes === null ? 'any' : 'today'}
                    onChange={(e) =>
                      setNeeds(needs.map((x) => (x === n ? { ...x, need_by_minutes: e.target.value === 'today' ? 60 : null } : x)))
                    }
                    className="rounded border border-slate-200 bg-white px-1 py-0.5 text-xs"
                  >
                    <option value="any">No rush</option>
                    <option value="today">Within 1 hour</option>
                  </select>
                  <button
                    type="button"
                    aria-label={`Remove ${p?.brand}`}
                    onClick={() => setNeeds(needs.filter((x) => x !== n))}
                    className="px-1 text-rose-500"
                  >
                    ✕
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      <OfferWallet offers={offers} setOffers={setOffers} />

      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <h2 className="text-sm font-bold uppercase tracking-wide text-slate-500">Would buy anyway (fillers)</h2>
        <p className="mt-1 text-xs text-slate-500">Restock items that can top up a basket that falls short of an offer.</p>
        <ProductPicker
          products={products}
          onPick={(k) => k && !fillers.includes(k) && setFillers([...fillers, k])}
          placeholder="Add a restock item…"
        />
        <div className="mt-2 flex flex-wrap gap-1.5">
          {fillers.map((k) => (
            <button
              key={k}
              type="button"
              onClick={() => setFillers(fillers.filter((x) => x !== k))}
              className="rounded-full bg-slate-100 px-2.5 py-1 text-xs"
            >
              {productByKey.get(k)?.brand} {productByKey.get(k)?.pack} ✕
            </button>
          ))}
        </div>
      </section>

      <button
        type="button"
        disabled={needs.length === 0 || loading}
        onClick={plan}
        className="w-full rounded-xl bg-orange-600 py-3 text-sm font-bold text-white shadow disabled:opacity-40"
      >
        {loading ? 'Planning…' : 'Plan my list'}
      </button>

      {error && <p className="rounded-xl bg-rose-50 p-3 text-sm text-rose-700">{error}</p>}
      {result && <Results result={result} />}
    </div>
  )
}

function ProductPicker({
  products,
  onPick,
  placeholder,
}: {
  products: Product[]
  onPick: (key: string) => void
  placeholder: string
}) {
  return (
    <select
      value=""
      onChange={(e) => onPick(e.target.value)}
      className="mt-2 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"
    >
      <option value="">{placeholder}</option>
      {products.map((p) => (
        <option key={p.key} value={p.key}>
          {p.icon} {p.brand} {p.pack}, from {formatINR(p.best.unit_price_paise)}
        </option>
      ))}
    </select>
  )
}

function OfferWallet({ offers, setOffers }: { offers: OfferIn[]; setOffers: (o: OfferIn[]) => void }) {
  const [platform, setPlatform] = useState<Platform>('amazon')
  const [template, setTemplate] = useState<OfferTemplate>('flat')
  const [minOrder, setMinOrder] = useState('500')
  const [value, setValue] = useState('50')
  const [rate, setRate] = useState('10')
  const [uses, setUses] = useState('2')
  const [formError, setFormError] = useState<string | null>(null)

  function add() {
    const min = parseRupees(minOrder)
    const val = parseRupees(value)
    const usesN = Number(uses)
    const rateN = Number(rate)
    if (min === null || val === null || !Number.isInteger(usesN) || usesN < 1) {
      setFormError('Enter amounts in rupees and at least 1 use.')
      return
    }
    if (template === 'pct_cap' && !(rateN > 0 && rateN <= 100)) {
      setFormError('Percent must be between 1 and 100.')
      return
    }
    setFormError(null)
    const id = `${platform}-${offers.length + 1}`
    setOffers([
      ...offers,
      {
        id,
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
      },
    ])
  }

  const input = 'w-full rounded-lg border border-slate-200 px-2 py-1.5 text-sm'
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <h2 className="text-sm font-bold uppercase tracking-wide text-slate-500">Offer wallet</h2>
      <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
        <label className="text-xs text-slate-500">
          Platform
          <select className={input} value={platform} onChange={(e) => setPlatform(e.target.value as Platform)}>
            {PLATFORMS.map((p) => (
              <option key={p} value={p}>
                {PLATFORM_META[p].name}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-slate-500">
          Type
          <select className={input} value={template} onChange={(e) => setTemplate(e.target.value as OfferTemplate)}>
            <option value="flat">₹ off on min order</option>
            <option value="pct_cap">% off up to a cap (bank)</option>
          </select>
        </label>
        <label className="text-xs text-slate-500">
          Min order (₹)
          <input className={input} inputMode="decimal" value={minOrder} onChange={(e) => setMinOrder(e.target.value)} />
        </label>
        {template === 'pct_cap' && (
          <label className="text-xs text-slate-500">
            Percent
            <input className={input} inputMode="decimal" value={rate} onChange={(e) => setRate(e.target.value)} />
          </label>
        )}
        <label className="text-xs text-slate-500">
          {template === 'flat' ? 'Cashback (₹)' : 'Cap (₹)'}
          <input className={input} inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} />
        </label>
        <label className="text-xs text-slate-500">
          Uses left
          <input className={input} inputMode="numeric" value={uses} onChange={(e) => setUses(e.target.value)} />
        </label>
      </div>
      <button type="button" onClick={add} className="mt-2 rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-bold text-white">
        Add offer
      </button>
      {formError && <p className="mt-1 text-xs text-rose-600">{formError}</p>}
      <ul className="mt-2 space-y-1 text-xs">
        {offers.map((o) => (
          <li key={o.id} className="flex items-center justify-between rounded-lg bg-amber-50 px-2 py-1.5">
            <span>
              <strong>{PLATFORM_META[o.platform].name}</strong>{' '}
              {o.kind === 'flat'
                ? `${formatINR(o.value_paise)} back on ${formatINR(o.min_order_paise)}+`
                : `${o.rate_bp / 100}% up to ${formatINR(o.cap_paise ?? 0)} on ${formatINR(o.min_order_paise)}+`}{' '}
              · {o.uses_left} use{o.uses_left === 1 ? '' : 's'}
            </span>
            <button type="button" aria-label="Remove offer" onClick={() => setOffers(offers.filter((x) => x !== o))} className="px-1 text-rose-500">
              ✕
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}

function Results({ result }: { result: PlanSetOut }) {
  const [active, setActive] = useState(0)
  const plan = result.plans[Math.min(active, result.plans.length - 1)]
  if (!plan) return null
  return (
    <section className="space-y-3">
      <div className="flex gap-2 overflow-x-auto">
        {result.plans.map((p, i) => (
          <button
            key={p.label}
            type="button"
            onClick={() => setActive(i)}
            className={`min-w-[9rem] flex-1 rounded-xl border p-3 text-left ${
              i === active ? 'border-orange-500 bg-orange-50' : 'border-slate-200 bg-white'
            }`}
          >
            <div className="text-xs font-bold text-slate-500">{PLAN_LABELS[p.label].title}</div>
            <div className="text-lg font-black">{formatINR(p.effective_cost_paise)}</div>
            <div className={`text-xs font-semibold ${p.savings_vs_baseline_paise > 0 ? 'text-emerald-700' : 'text-slate-500'}`}>
              {p.savings_vs_baseline_paise > 0
                ? `Save ${formatINR(p.savings_vs_baseline_paise)}`
                : p.savings_vs_baseline_paise < 0
                  ? `${formatINR(-p.savings_vs_baseline_paise)} more`
                  : 'Same as one order each'}
            </div>
          </button>
        ))}
      </div>

      <p className="text-xs text-slate-500">
        {PLAN_LABELS[plan.label].blurb}. Compared with one order per platform: {formatINR(result.baseline.total_net_paise)}.
      </p>

      {plan.reasons.length > 0 && (
        <ul className="space-y-1 rounded-xl bg-sky-50 p-3 text-sm text-sky-900">
          {plan.reasons.map((r, i) => (
            <li key={i}>• {r.text}</li>
          ))}
        </ul>
      )}

      {plan.orders.map((o, i) => (
        <OrderCard key={i} order={o} />
      ))}

      {plan.unpriced.length > 0 && (
        <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-800">
          No listing meets the delivery time for: {plan.unpriced.join(', ')}.
        </p>
      )}
    </section>
  )
}

function OrderCard({ order }: { order: OrderOut }) {
  const meta = PLATFORM_META[order.platform]
  const pending = order.status === 'pending'
  return (
    <article className={`rounded-2xl border bg-white p-4 shadow-sm ${pending ? 'border-amber-400' : 'border-slate-200'}`}>
      <header className="flex items-center justify-between">
        <span className="flex items-center gap-2 text-sm font-bold">
          <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: meta.color }} />
          {meta.name}
          {pending && <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-extrabold uppercase text-amber-800">Pending</span>}
        </span>
        <span className="text-sm font-black">{formatINR(order.net_paise)}</span>
      </header>
      {pending && order.shortfall_paise !== null && (
        <p className="mt-1 text-xs text-amber-800">
          {formatINR(order.shortfall_paise)} short before fillers. Place it once the extra items are added.
        </p>
      )}
      <ul className="mt-2 space-y-1 text-sm">
        {order.lines.map((l) => (
          <li key={l.line_id} className="flex justify-between gap-2">
            <span className="min-w-0 truncate">
              {l.is_filler && <span className="mr-1 rounded bg-slate-100 px-1 text-[10px] font-bold uppercase">filler</span>}
              {l.title} <span className="text-slate-400">{l.pack_label}</span>
            </span>
            <span className="shrink-0 font-semibold">{formatINR(l.unit_price_paise * l.qty)}</span>
          </li>
        ))}
      </ul>
      <dl className="mt-2 space-y-0.5 border-t border-slate-100 pt-2 text-xs text-slate-600">
        <div className="flex justify-between">
          <dt>Subtotal</dt>
          <dd>{formatINR(order.subtotal_paise)}</dd>
        </div>
        <div className="flex justify-between">
          <dt>Fees</dt>
          <dd>{order.fees.total === 0 ? 'Free' : formatINR(order.fees.total)}</dd>
        </div>
        {order.offers_applied.map((a) => (
          <div key={a.offer_id} className="flex justify-between text-emerald-700">
            <dt>Offer {a.offer_id}</dt>
            <dd>-{formatINR(a.effective_value_paise)}</dd>
          </div>
        ))}
      </dl>
    </article>
  )
}
