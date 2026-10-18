import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  api,
  PLATFORM_META,
  PLATFORMS,
  type LabelledPlanOut,
  type ListDetail,
  type ListSummary,
  type OrderOut,
  type Platform,
  type PlanSetOut,
  type SavedNeed,
} from '../../lib/api'
import { formatINR } from '../../lib/money'
import { usePreference } from '../../lib/preference'
import { useProducts, type Product } from '../../lib/products'
import { Card, ErrorNote, SectionTitle } from '../../lib/ui'

const PLAN_LABELS: Record<LabelledPlanOut['label'], { title: string; blurb: string }> = {
  cheapest_now: { title: 'Cheapest now', blurb: 'Everything ordered today' },
  max_savings: { title: 'Max savings', blurb: 'Holds one basket until you top it up' },
  fastest: { title: 'Fastest', blurb: 'Quickest delivery for every item' },
}

export default function PlansPage({ onAccepted }: { onAccepted: () => void }) {
  const [members, setMembers] = usePreference<Platform[]>('members', ['amazon', 'instamart', 'flipkart'])
  const [fillers, setFillers] = usePreference<string[]>('fillers', [])
  const [listId, setListId] = usePreference<number | null>('listId', null)
  const [lists, setLists] = useState<ListSummary[]>([])
  const [list, setList] = useState<ListDetail | null>(null)
  const [result, setResult] = useState<(PlanSetOut & { plan_run_id: number }) | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const { deals, products } = useProducts(members)
  const productByKey = useMemo(() => new Map(products.map((p) => [p.key, p])), [products])

  const loadLists = useCallback(async () => {
    try {
      let all = await api.lists()
      if (all.length === 0) {
        await api.createList('This month', 'monthly')
        all = await api.lists()
      }
      setLists(all)
      if (listId === null || !all.some((l) => l.id === listId)) setListId(all[0].id)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [listId, setListId])

  const loadList = useCallback(async () => {
    if (listId === null) return
    try {
      setList(await api.list(listId))
    } catch (e) {
      setError((e as Error).message)
    }
  }, [listId])

  useEffect(() => {
    void loadLists()
  }, [loadLists])
  useEffect(() => {
    void loadList()
  }, [loadList])

  const openNeeds = (list?.needs ?? []).filter((n) => n.status === 'open')

  async function run(action: () => Promise<unknown>) {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  function addNeed(key: string) {
    const p = productByKey.get(key)
    if (!p || listId === null) return
    const lineId = `${p.brand} ${p.pack}`
    if (openNeeds.some((n) => n.line_id === lineId)) return
    void run(async () => {
      await api.addNeed(listId, { line_id: lineId, product_key: key, family_key: null, quantity: null, qty: 1, need_by_minutes: null, lock_platform: null })
      setResult(null)
      await Promise.all([loadList(), loadLists()])
    })
  }

  function patchNeed(n: SavedNeed, patch: Partial<SavedNeed>) {
    void run(async () => {
      await api.updateNeed(n.id, patch)
      setResult(null)
      await Promise.all([loadList(), loadLists()])
    })
  }

  function dropNeed(n: SavedNeed) {
    void run(async () => {
      await api.dropNeed(n.id)
      setResult(null)
      await Promise.all([loadList(), loadLists()])
    })
  }

  function plan() {
    if (listId === null) return
    void run(async () => {
      const fillerListings = deals
        .filter((d) => fillers.includes(d.product_key) && !openNeeds.some((n) => n.product_key === d.product_key))
        .map((d) => ({ filler_id: `${d.brand} ${d.pack_label} (${PLATFORM_META[d.platform].name})`, listing_id: d.id, score: 3 }))
      setResult(await api.planList(listId, members, fillerListings))
    })
  }

  function accept(label: string) {
    if (!result) return
    void run(async () => {
      await api.accept(result.plan_run_id, label)
      setResult(null)
      await Promise.all([loadList(), loadLists()])
      onAccepted()
    })
  }

  function newList() {
    const name = `List ${new Date().toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}`
    void run(async () => {
      const created = await api.createList(name, 'quick')
      await loadLists()
      setListId(created.id)
    })
  }

  return (
    <div className="space-y-5">
      <Card>
        <SectionTitle>Memberships</SectionTitle>
        <div className="mt-2 flex flex-wrap gap-2">
          {PLATFORMS.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => {
                setMembers(members.includes(p) ? members.filter((x) => x !== p) : [...members, p])
                setResult(null)
              }}
              className={`rounded-full border px-3 py-1 text-xs font-semibold ${
                members.includes(p) ? 'border-emerald-500 bg-emerald-50 text-emerald-800' : 'border-slate-200 bg-slate-50 text-slate-500'
              }`}
            >
              {PLATFORM_META[p].membership} {members.includes(p) ? 'on' : 'off'}
            </button>
          ))}
        </div>
      </Card>

      <Card>
        <div className="flex items-center justify-between gap-2">
          <select
            aria-label="Shopping list"
            value={listId ?? ''}
            onChange={(e) => {
              setListId(Number(e.target.value))
              setResult(null)
            }}
            className="min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm font-bold"
          >
            {lists.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name} ({l.open_needs} to buy)
              </option>
            ))}
          </select>
          <button type="button" onClick={newList} className="shrink-0 text-xs font-semibold text-orange-700">
            + New list
          </button>
        </div>
        <ProductPicker products={products} onPick={addNeed} placeholder="Add an item…" />
        {openNeeds.length === 0 ? (
          <p className="mt-3 text-sm text-slate-500">Nothing to buy yet. Mark items "no rush" so they can wait for a better basket.</p>
        ) : (
          <ul className="mt-3 divide-y divide-slate-100">
            {openNeeds.map((n) => {
              const p = productByKey.get(n.product_key ?? '') ?? products.find((x) => x.family === n.family_key && x.pack === n.quantity)
              return (
                <li key={n.id} className="flex flex-wrap items-center gap-2 py-2 text-sm">
                  <span className="text-lg">{p?.icon}</span>
                  <span className="min-w-0 flex-1 truncate font-semibold">{n.line_id}</span>
                  <label className="flex items-center gap-1 text-xs text-slate-600">
                    <input
                      type="checkbox"
                      checked={n.family_key !== null}
                      disabled={!p}
                      onChange={(e) =>
                        p &&
                        patchNeed(
                          n,
                          e.target.checked
                            ? { product_key: null, family_key: p.family, quantity: p.pack }
                            : { product_key: p.key, family_key: null, quantity: null },
                        )
                      }
                    />
                    Any brand
                  </label>
                  <select
                    aria-label="When do you need it"
                    value={n.need_by_minutes === null ? 'any' : 'today'}
                    onChange={(e) => patchNeed(n, { need_by_minutes: e.target.value === 'today' ? 60 : null })}
                    className="rounded border border-slate-200 bg-white px-1 py-0.5 text-xs"
                  >
                    <option value="any">No rush</option>
                    <option value="today">Within 1 hour</option>
                  </select>
                  <button type="button" aria-label={`Remove ${n.line_id}`} onClick={() => dropNeed(n)} className="px-1 text-rose-500">
                    ✕
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </Card>

      <Card>
        <SectionTitle>Would buy anyway (fillers)</SectionTitle>
        <p className="mt-1 text-xs text-slate-500">Restock items that can top up a basket that falls short of an offer.</p>
        <ProductPicker
          products={products}
          onPick={(k) => k && !fillers.includes(k) && setFillers([...fillers, k])}
          placeholder="Add a restock item…"
        />
        <div className="mt-2 flex flex-wrap gap-1.5">
          {fillers.map((k) => (
            <button key={k} type="button" onClick={() => setFillers(fillers.filter((x) => x !== k))} className="rounded-full bg-slate-100 px-2.5 py-1 text-xs">
              {productByKey.get(k)?.brand} {productByKey.get(k)?.pack} ✕
            </button>
          ))}
        </div>
      </Card>

      <button
        type="button"
        disabled={openNeeds.length === 0 || busy}
        onClick={plan}
        className="w-full rounded-xl bg-orange-600 py-3 text-sm font-bold text-white shadow disabled:opacity-40"
      >
        {busy ? 'Working…' : 'Plan my list with my offers'}
      </button>

      <ErrorNote error={error} />
      {result && <Results result={result} onAccept={accept} busy={busy} />}
    </div>
  )
}

function ProductPicker({ products, onPick, placeholder }: { products: Product[]; onPick: (key: string) => void; placeholder: string }) {
  return (
    <select value="" onChange={(e) => onPick(e.target.value)} className="mt-2 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm">
      <option value="">{placeholder}</option>
      {products.map((p) => (
        <option key={p.key} value={p.key}>
          {p.icon} {p.brand} {p.pack}, from {formatINR(p.best.unit_price_paise)}
        </option>
      ))}
    </select>
  )
}

function Results({ result, onAccept, busy }: { result: PlanSetOut; onAccept: (label: string) => void; busy: boolean }) {
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

      <button
        type="button"
        disabled={busy}
        onClick={() => onAccept(plan.label)}
        className="w-full rounded-xl bg-slate-900 py-3 text-sm font-bold text-white disabled:opacity-40"
      >
        Use “{PLAN_LABELS[plan.label].title}”: create {plan.orders.length} basket{plan.orders.length === 1 ? '' : 's'}
      </button>

      {plan.unpriced.length > 0 && (
        <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-800">
          No listing meets the delivery time for: {plan.unpriced.join(', ')}.
        </p>
      )}
    </section>
  )
}

export function OrderCard({ order }: { order: OrderOut }) {
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
              {l.title}{' '}
              <span className="text-slate-400">
                {l.packs > 1 ? `${l.packs} × ` : ''}
                {l.pack_label}
              </span>
            </span>
            <span className="shrink-0 font-semibold">{formatINR(l.line_total_paise)}</span>
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
