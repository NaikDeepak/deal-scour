import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, PLATFORM_META, type Basket, type BasketStatus, type Deal, type Ledger, type Platform } from '../../lib/api'
import { formatINR, parseRupees } from '../../lib/money'
import { usePreference } from '../../lib/preference'
import { useProducts } from '../../lib/products'
import { Card, ErrorNote, inputClass, SectionTitle } from '../../lib/ui'
import { buildCartItemsFromBasket, triggerAddToCart } from '../plans/cartBuilder'

const GROUPS: { status: BasketStatus; title: string; hint: string }[] = [
  { status: 'pending', title: 'Pending: waiting for top-up', hint: 'Short of an offer threshold. Add things you need anyway, or place it without the offer.' },
  { status: 'ready', title: 'Ready to order', hint: 'Open the app, add these items, check out, then mark it placed.' },
  { status: 'placed', title: 'Placed: cashback to confirm', hint: 'Record cashback when it lands.' },
  { status: 'settled', title: 'Done', hint: '' },
]

export default function BasketsPage() {
  const [baskets, setBaskets] = useState<Basket[]>([])
  const [ledger, setLedger] = useState<Ledger | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [members] = usePreference<Platform[]>('members', ['amazon', 'instamart', 'flipkart'])
  const { deals } = useProducts(members)

  const load = useCallback(async () => {
    try {
      const [b, l] = await Promise.all([api.baskets(), api.ledger()])
      setBaskets(b)
      setLedger(l)
    } catch (e) {
      setError((e as Error).message)
    }
  }, [])
  useEffect(() => {
    void load()
  }, [load])

  async function act(action: () => Promise<unknown>) {
    setError(null)
    try {
      await action()
      await load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="space-y-4">
      {ledger && (
        <Card>
          <SectionTitle>This month</SectionTitle>
          <dl className="mt-2 grid grid-cols-3 gap-2 text-center">
            <Stat label="Paid" value={formatINR(ledger.paid_paise)} />
            <Stat label="Offers earned" value={formatINR(ledger.offer_expected_paise)} />
            <Stat label="Cashback pending" value={formatINR(ledger.cashback_pending_paise)} />
          </dl>
        </Card>
      )}
      <ErrorNote error={error} />
      {baskets.length === 0 && <p className="text-sm text-slate-500">No baskets yet. Plan a list and choose “Use this plan”.</p>}
      {GROUPS.map((g) => {
        const items = baskets.filter((b) => b.status === g.status)
        if (items.length === 0) return null
        return (
          <section key={g.status} className="space-y-2">
            <SectionTitle>{g.title}</SectionTitle>
            {g.hint && <p className="text-xs text-slate-500">{g.hint}</p>}
            {items.map((b) => (
              <BasketCard key={b.id} basket={b} deals={deals} act={act} />
            ))}
          </section>
        )
      })}
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[11px] font-semibold uppercase text-slate-500">{label}</dt>
      <dd className="text-base font-black">{value}</dd>
    </div>
  )
}

function BasketCard({
  basket: b,
  deals,
  act,
}: {
  basket: Basket
  deals: Deal[]
  act: (f: () => Promise<unknown>) => Promise<void>
}) {
  const meta = PLATFORM_META[b.platform]
  const subtotal = b.lines.reduce((s, l) => s + l.line_total_paise, 0)
  const [amount, setAmount] = useState('')
  const sameStore = useMemo(() => deals.filter((d) => d.platform === b.platform), [deals, b.platform])
  const storeUrl = sameStore[0]?.url

  function paise(fallback: number): number | null {
    return amount.trim() === '' ? fallback : parseRupees(amount)
  }

  return (
    <article className={`rounded-2xl border bg-white p-4 shadow-sm ${b.status === 'pending' ? 'border-amber-400' : 'border-slate-200'}`}>
      <header className="flex items-center justify-between">
        <span className="flex items-center gap-2 text-sm font-bold">
          <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: meta.color }} />
          {meta.name}
        </span>
        <span className="text-sm font-black">{formatINR(b.actual_paid_paise ?? b.planned_net_paise)}</span>
      </header>

      {b.status === 'pending' && b.threshold_paise !== null && (
        <div className="mt-2">
          <div className="h-2 overflow-hidden rounded-full bg-amber-100">
            <div className="h-2 bg-amber-500" style={{ width: `${Math.min(100, Math.round((subtotal / b.threshold_paise) * 100))}%` }} />
          </div>
          <p className="mt-1 text-xs text-amber-800">
            {formatINR(subtotal)} of {formatINR(b.threshold_paise)}: {formatINR(b.shortfall_paise ?? 0)} short of offer {b.target_offer_code}
          </p>
        </div>
      )}

      <ul className="mt-2 space-y-1 text-sm">
        {b.lines.map((l) => (
          <li key={l.id} className="flex justify-between gap-2">
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

      {b.offer_value_expected_paise > 0 && (
        <p className="mt-2 text-xs font-semibold text-emerald-700">
          Offer {b.target_offer_code ?? ''} worth {formatINR(b.offer_value_expected_paise)}
          {b.offer_value_received_paise !== null ? ` · received ${formatINR(b.offer_value_received_paise)}` : ''}
        </p>
      )}

      <div className="mt-3 space-y-2 border-t border-slate-100 pt-3">
        {b.status === 'pending' && (
          <>
            <select
              value=""
              onChange={(e) => {
                const d = sameStore.find((x) => x.id === e.target.value)
                if (d) void act(() => api.addLine(b.id, d.id, `${d.brand} ${d.pack_label}`))
              }}
              className={inputClass}
            >
              <option value="">Top up with something you need from {meta.name}…</option>
              {sameStore.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.icon} {d.brand} {d.pack_label}: {formatINR(d.unit_price_paise)}
                </option>
              ))}
            </select>
            <div className="flex gap-2">
              <button type="button" onClick={() => act(() => api.place(b.id, subtotal, true))} className="flex-1 rounded-lg border border-slate-300 py-1.5 text-xs font-bold">
                Order now without the offer
              </button>
              <button type="button" onClick={() => act(() => api.release(b.id))} className="flex-1 rounded-lg border border-rose-200 py-1.5 text-xs font-bold text-rose-700">
                Give up (items back to list)
              </button>
            </div>
          </>
        )}

        {b.status === 'ready' && (
          <>
            <button
              type="button"
              onClick={() => {
                const extInstalled =
                  typeof document !== 'undefined' &&
                  document.documentElement.getAttribute('data-dealscour-extension') === 'installed'
                triggerAddToCart(buildCartItemsFromBasket(b, deals), extInstalled)
              }}
              className="block w-full rounded-lg bg-emerald-700 py-2 text-center text-xs font-bold text-white hover:bg-emerald-800"
            >
              🛒 Auto-Add {b.lines.length} Item{b.lines.length === 1 ? '' : 's'} to {meta.name} Cart
            </button>
            {storeUrl && (
              <a href={storeUrl} target="_blank" rel="noopener noreferrer" className="block rounded-lg bg-slate-100 py-1.5 text-center text-xs font-bold">
                Open {meta.name} ↗
              </a>
            )}
            <div className="flex gap-2">
              <input
                className={inputClass}
                inputMode="decimal"
                placeholder={`Paid (₹), default ${formatINR(b.planned_net_paise)}`}
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
              />
              <button
                type="button"
                onClick={() => {
                  const p = paise(b.planned_net_paise)
                  if (p !== null) void act(() => api.place(b.id, p))
                }}
                className="shrink-0 rounded-lg bg-slate-900 px-3 text-xs font-bold text-white"
              >
                Mark placed
              </button>
            </div>
          </>
        )}

        {b.status === 'placed' && (
          <div className="flex gap-2">
            <input
              className={inputClass}
              inputMode="decimal"
              placeholder={`Cashback received (₹), default ${formatINR(b.offer_value_expected_paise)}`}
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
            />
            <button
              type="button"
              onClick={() => {
                const p = paise(b.offer_value_expected_paise)
                if (p !== null) void act(() => api.cashback(b.id, p))
              }}
              className="shrink-0 rounded-lg bg-emerald-700 px-3 text-xs font-bold text-white"
            >
              Cashback received
            </button>
          </div>
        )}
      </div>
    </article>
  )
}
