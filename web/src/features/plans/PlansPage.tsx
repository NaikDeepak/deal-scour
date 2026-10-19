import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  api,
  catalog,
  PLATFORM_META,
  PLATFORMS,
  type CatalogProductItem,
  type Deal,
  type LabelledPlanOut,
  type ListDetail,
  type ListSummary,
  type NeedIn,
  type OrderOut,
  type Platform,
  type PlanSetOut,
  type SavedNeed,
  type ScourTarget,
} from '../../lib/api'
import { formatINR } from '../../lib/money'
import { usePreference } from '../../lib/preference'
import { useProducts, type Product } from '../../lib/products'
import { Card, ErrorNote, SectionTitle } from '../../lib/ui'
import FindOnShops from '../catalog/FindOnShops'
import CatalogPicker, { CatalogNeedFindButton } from '../list/CatalogPicker'
import {
  buildCartItemsFromOrder,
  processPriceCaptures,
  triggerAddToCart,
  type CartItemResult,
  type PriceConfirmationItem,
} from './cartBuilder'
import ComparisonMatrix from './ComparisonMatrix'

const PLAN_LABELS: Record<LabelledPlanOut['label'], { title: string; blurb: string }> = {
  cheapest_now: { title: 'Cheapest now', blurb: 'Everything ordered today' },
  max_savings: { title: 'Max savings', blurb: 'Holds one basket until you top it up' },
  fastest: { title: 'Fastest', blurb: 'Quickest delivery for every item' },
}

interface ExtensionScourResult {
  listing_id: string
  ok: boolean
  listed_paise?: number
  mrp_paise?: number
  in_stock?: boolean
  eta_minutes?: number | null
  error?: string
}

export default function PlansPage({
  onAccepted,
  initialOpenNeeds,
  initialCatalogQuery,
  initialCatalogItems,
}: {
  onAccepted: () => void
  initialOpenNeeds?: SavedNeed[]
  initialCatalogQuery?: string
  initialCatalogItems?: CatalogProductItem[]
}) {
  const [members, setMembers] = usePreference<Platform[]>('members', ['amazon', 'instamart', 'flipkart'])
  const [fillers, setFillers] = usePreference<string[]>('fillers', [])
  const [listId, setListId] = usePreference<number | null>('listId', null)
  const [lists, setLists] = useState<ListSummary[]>([])
  const [list, setList] = useState<ListDetail | null>(null)
  const [result, setResult] = useState<(PlanSetOut & { plan_run_id: number; no_prices: string[] }) | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)
  const [extReady, setExtReady] = useState(
    () => typeof document !== 'undefined' && document.documentElement.getAttribute('data-dealscour-extension') === 'installed',
  )
  const [scourNote, setScourNote] = useState<string | null>(null)
  const [pendingConfirmations, setPendingConfirmations] = useState<PriceConfirmationItem[]>([])
  const [catalogByLineId, setCatalogByLineId] = useState<Map<string, CatalogProductItem>>(() => new Map())
  const [findingProduct, setFindingProduct] = useState<CatalogProductItem | null>(null)
  const { deals, products } = useProducts(members, refreshKey)
  const productByKey = useMemo(() => new Map(products.map((p) => [p.key, p])), [products])
  const dealById = useMemo(() => new Map(deals.map((d) => [d.id, d])), [deals])

  async function handleConfirmPrice(item: PriceConfirmationItem) {
    try {
      await api.capturePrice({
        listing_id: item.listing_id,
        listed_paise: item.new_price_paise,
        mrp_paise: item.mrp_paise,
        in_stock: item.in_stock,
        eta_minutes: item.eta_minutes,
        confirm: true,
      })
      setPendingConfirmations((prev) => prev.filter((p) => p.listing_id !== item.listing_id))
      setRefreshKey((k) => k + 1)
      if (listId !== null) {
        await executePlan(listId)
      }
    } catch (e) {
      setError((e as Error).message)
    }
  }

  function handleSkipPrice(item: PriceConfirmationItem) {
    setPendingConfirmations((prev) => prev.filter((p) => p.listing_id !== item.listing_id))
  }

  useEffect(() => {
    function onMessage(e: MessageEvent) {
      if (e.source !== window || !e.data || typeof e.data.type !== 'string') return
      if (e.data.type === 'DEALSCOUR_EXTENSION_READY') {
        setExtReady(true)
      } else if (e.data.type === 'DEALSCOUR_SCOUR_PROGRESS') {
        const { current, total, platform, title } = e.data as { current: number; total: number; platform: Platform; title: string }
        const pName = PLATFORM_META[platform]?.name ?? platform
        setScourNote(`Scouring ${current}/${total}: ${pName} · ${title}…`)
      } else if (e.data.type === 'DEALSCOUR_CART_PROGRESS') {
        const { current, total, platform, title } = e.data as { current: number; total: number; platform: Platform; title: string }
        const pName = PLATFORM_META[platform]?.name ?? platform
        setScourNote(`Adding ${current}/${total} to ${pName} cart: ${title}…`)
      } else if (e.data.type === 'DEALSCOUR_ADD_TO_CART_COMPLETE') {
        setScourNote('All basket items processed! Check the open portal tab(s) to review your cart and pay.')
      }
    }
    window.addEventListener('message', onMessage)
    window.postMessage({ type: 'DEALSCOUR_PING_EXTENSION' }, window.location.origin)
    return () => window.removeEventListener('message', onMessage)
  }, [])

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

  const openNeeds = list ? list.needs.filter((n) => n.status === 'open') : (initialOpenNeeds ?? [])

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

  function addCatalogNeed(needIn: Omit<NeedIn, 'line_id'> & { line_id: string }, item: CatalogProductItem) {
    setCatalogByLineId((prev) => new Map(prev).set(needIn.line_id, item))
    if (listId === null) return
    if (openNeeds.some((n) => n.line_id === needIn.line_id)) return
    void run(async () => {
      await api.addNeed(listId, needIn)
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

  async function executePlan(currentListId: number) {
    const fillerListings = deals
      .filter((d) => fillers.includes(d.product_key) && !openNeeds.some((n) => n.product_key === d.product_key))
      .map((d) => ({ filler_id: `${d.brand} ${d.pack_label} (${PLATFORM_META[d.platform].name})`, listing_id: d.id, score: 3 }))
    setResult(await api.planList(currentListId, members, fillerListings))
  }

  function plan() {
    if (listId === null) return
    void run(async () => {
      await executePlan(listId)
    })
  }

  function oneClickDryfruitsDealFinder() {
    if (listId === null) return
    void run(async () => {
      setScourNote('Loading 8 Dryfruits & Seeds (500g each) across all 5 portals + active offers…')
      const bundleRes = await api.applyQuickBundle(listId, 'dryfruits_500g')
      setRefreshKey((k) => k + 1)
      await Promise.all([loadList(), loadLists()])
      await executePlan(listId)
      if (bundleRes.unpriced_families && bundleRes.unpriced_families.length > 0) {
        setScourNote('Added the dry fruits and seeds. Planned the ones that have prices.')
      } else {
        setScourNote('Loaded all 8 Dryfruits & Seeds (500g each) and calculated optimal split!')
      }
    })
  }

  function runExtensionScour(targets: ScourTarget[]): Promise<ExtensionScourResult[]> {
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        window.removeEventListener('message', handler)
        reject(new Error('Extension scour timed out'))
      }, Math.max(20000, targets.length * 14000))

      function handler(e: MessageEvent) {
        if (e.source !== window || !e.data || typeof e.data.type !== 'string') return
        if (e.data.type === 'DEALSCOUR_SCOUR_COMPLETE') {
          clearTimeout(timeout)
          window.removeEventListener('message', handler)
          resolve((e.data.results as ExtensionScourResult[]) ?? [])
        } else if (e.data.type === 'DEALSCOUR_SCOUR_ERROR') {
          clearTimeout(timeout)
          window.removeEventListener('message', handler)
          reject(new Error(String(e.data.error ?? 'Extension error')))
        }
      }

      window.addEventListener('message', handler)
      window.postMessage({ type: 'DEALSCOUR_SCOUR_REQUEST', targets }, window.location.origin)
    })
  }

  function scourAndPlan() {
    if (listId === null) return
    void run(async () => {
      setScourNote('Preparing cross-platform scour targets…')
      const { targets } = await api.scourTargets(listId)
      if (extReady && targets.length > 0) {
        const results = await runExtensionScour(targets)
        const oldPriceMap = new Map(deals.map((d) => [d.id, d.unit_price_paise]))
        const batch = await processPriceCaptures(
          results,
          (payload) => api.capturePrice(payload),
          targets,
          oldPriceMap,
        )
        if (batch.pendingConfirmations.length > 0) {
          setPendingConfirmations((prev) => [...prev, ...batch.pendingConfirmations])
        }
        setRefreshKey((k) => k + 1)
        setScourNote(
          `Captured ${batch.savedCount}/${targets.length} live prices.` +
            (batch.pendingConfirmations.length > 0
              ? ` ${batch.pendingConfirmations.length} price change(s) need confirmation below.`
              : ''),
        )
      } else {
        try {
          const { queued } = await catalog.refreshPrices()
          setScourNote(
            queued > 0
              ? `Queued ${queued} background check(s). Install the DealScour extension to check Blinkit, Zepto and Instamart prices too.`
              : 'Optimized with latest stored prices. Install the DealScour extension to check Blinkit, Zepto and Instamart prices too.',
          )
        } catch {
          setScourNote('Optimized with latest stored prices.')
        }
      }
      await executePlan(listId)
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

        <div className="mt-2.5 flex flex-wrap items-center gap-2 rounded-xl border border-amber-200 bg-amber-50/70 p-2.5">
          <span className="text-xs font-bold text-amber-900">Zero-Manual One-Click Preset:</span>
          <button
            type="button"
            disabled={busy || listId === null}
            onClick={oneClickDryfruitsDealFinder}
            className="rounded-lg bg-amber-600 px-3 py-1.5 text-xs font-bold text-white shadow-2xs hover:bg-amber-700 disabled:opacity-40"
          >
            Add dry fruits and seeds (8 items, 500g each)
          </button>
        </div>

        <CatalogPicker
          products={products}
          placeholder="Add an item…"
          extReady={extReady}
          initialQuery={initialCatalogQuery}
          initialCatalogItems={initialCatalogItems}
          onPickProduct={addNeed}
          onPickCatalogNeed={addCatalogNeed}
          onFindOnShops={setFindingProduct}
          onTrackedListings={() => setRefreshKey((k) => k + 1)}
        />
        {openNeeds.length === 0 ? (
          <p className="mt-3 text-sm text-slate-500">Nothing to buy yet. Click the 1-Click Dryfruits button above or pick items below.</p>
        ) : (
          <ul className="mt-3 divide-y divide-slate-100">
            {openNeeds.map((n) => {
              const seedProduct =
                productByKey.get(n.product_key ?? '') ??
                products.find((x) => `${x.brand} ${x.pack}` === n.line_id)
              const p =
                seedProduct ??
                products.find((x) => x.family === n.family_key && x.pack === n.quantity)
              const isCatalogNeed =
                catalogByLineId.has(n.line_id) || (!seedProduct && n.family_key !== null)
              return (
                <li key={n.id} className="flex flex-wrap items-center gap-2 py-2 text-sm">
                  <span className="text-lg">{p?.icon}</span>
                  <span className="min-w-0 flex-1 truncate font-semibold">{n.line_id}</span>
                  {isCatalogNeed && (
                    <CatalogNeedFindButton
                      need={n}
                      catalogItem={catalogByLineId.get(n.line_id)}
                      onFindOnShops={setFindingProduct}
                    />
                  )}
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

      {findingProduct && (
        <FindOnShops
          product={findingProduct}
          extReady={extReady}
          onClose={() => setFindingProduct(null)}
          onTracked={() => setRefreshKey((k) => k + 1)}
        />
      )}

      <ComparisonMatrix needs={openNeeds} deals={deals} />

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

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <button
          type="button"
          disabled={openNeeds.length === 0 || busy}
          onClick={scourAndPlan}
          className="w-full rounded-xl bg-emerald-700 py-3 text-sm font-bold text-white shadow disabled:opacity-40"
        >
          {busy ? 'Checking prices…' : extReady ? 'Check live prices and plan' : 'Refresh prices and plan'}
        </button>
        <button
          type="button"
          disabled={openNeeds.length === 0 || busy}
          onClick={plan}
          className="w-full rounded-xl bg-orange-600 py-3 text-sm font-bold text-white shadow disabled:opacity-40"
        >
          {busy ? 'Working…' : 'Plan my list with my offers'}
        </button>
      </div>

      {scourNote && <p className="rounded-xl bg-slate-100 px-3 py-2 text-xs text-slate-700">{scourNote}</p>}
      {result && result.no_prices.length > 0 && (
        <p className="rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-800">
          No prices yet for: {result.no_prices.map((key) => key.replace(/_/g, ' ')).join(', ')}. Add a product link on the Prices tab
          to include them.
        </p>
      )}

      {pendingConfirmations.length > 0 && (
        <Card>
          <SectionTitle>Check these prices</SectionTitle>
          <p className="mt-1 text-xs text-slate-500">
            These prices changed by more than 60% compared to recent data. Check that the page was read correctly.
          </p>
          <div className="mt-3 space-y-2">
            {pendingConfirmations.map((item) => (
              <div
                key={item.listing_id}
                className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 rounded-xl border border-amber-200 bg-amber-50/50 p-3 text-xs"
              >
                <div>
                  <div className="font-bold text-slate-800">
                    <span className="capitalize font-semibold text-slate-500 mr-1.5">[{item.platform}]</span>
                    {item.title}
                  </div>
                  <div className="text-slate-600 mt-0.5">
                    {item.old_price_paise !== null ? (
                      <>
                        Was <span className="line-through">{formatINR(item.old_price_paise)}</span> → Now{' '}
                        <span className="font-bold text-slate-900">{formatINR(item.new_price_paise)}</span>
                      </>
                    ) : (
                      <>
                        New price: <span className="font-bold text-slate-900">{formatINR(item.new_price_paise)}</span>
                      </>
                    )}
                  </div>
                </div>
                <div className="flex gap-2 shrink-0">
                  <button
                    type="button"
                    onClick={() => void handleConfirmPrice(item)}
                    className="rounded-lg bg-emerald-700 px-3 py-1.5 font-bold text-white hover:bg-emerald-800"
                  >
                    Looks right
                  </button>
                  <button
                    type="button"
                    onClick={() => handleSkipPrice(item)}
                    className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 font-bold text-slate-600 hover:bg-slate-50"
                  >
                    Skip
                  </button>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      <ErrorNote error={error} />
      {result && (
        <Results
          result={result}
          dealById={dealById}
          extReady={extReady}
          onStatus={setScourNote}
          onAccept={accept}
          busy={busy}
        />
      )}
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

function Results({
  result,
  dealById,
  extReady,
  onStatus,
  onAccept,
  busy,
}: {
  result: PlanSetOut
  dealById: Map<string, Deal>
  extReady: boolean
  onStatus?: (msg: string) => void
  onAccept: (label: string) => void
  busy: boolean
}) {
  const [active, setActive] = useState(0)
  const plan = result.plans[Math.min(active, result.plans.length - 1)]
  if (!plan) return null

  function addAllOrdersToCarts() {
    const allItems = plan.orders.flatMap((o) => buildCartItemsFromOrder(o, dealById))
    triggerAddToCart(allItems, extReady, onStatus)
  }

  return (
    <section className="space-y-3">
      <div className="rounded-2xl border border-emerald-200 bg-emerald-50/80 p-3.5 text-slate-900">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <div className="text-[11px] font-bold uppercase tracking-wide text-emerald-800">Optimal Delivery Summary</div>
            <div className="text-xl font-black text-slate-900">
              Pay {formatINR(plan.effective_cost_paise)}{' '}
              <span className="text-xs font-normal text-slate-600">
                across {plan.orders.length} order{plan.orders.length === 1 ? '' : 's'}
              </span>
            </div>
          </div>
          <div className="text-right">
            <div className="text-sm font-extrabold text-emerald-700">
              {plan.savings_vs_baseline_paise > 0
                ? `Total Saved: ${formatINR(plan.savings_vs_baseline_paise)}`
                : 'Optimal Baseline'}
            </div>
            <div className="text-[11px] text-slate-600">vs {formatINR(result.baseline.total_net_paise)} single-order baseline</div>
          </div>
        </div>
        <div className="mt-2 flex flex-wrap gap-2 text-xs">
          <span className="rounded-lg bg-white px-2 py-1 font-semibold text-slate-700 shadow-2xs">
            Items: {formatINR(plan.total_subtotal_paise)}
          </span>
          <span className="rounded-lg bg-white px-2 py-1 font-semibold text-emerald-700 shadow-2xs">
            Offer Cashback: -{formatINR(plan.total_offer_value_paise)}
          </span>
          <span className="rounded-lg bg-white px-2 py-1 font-semibold text-slate-700 shadow-2xs">
            Delivery/Fees: {plan.total_fees_paise === 0 ? 'Free' : formatINR(plan.total_fees_paise)}
          </span>
        </div>
        <button
          type="button"
          onClick={addAllOrdersToCarts}
          className="mt-3 w-full rounded-xl bg-emerald-700 py-2.5 text-xs font-extrabold text-white shadow hover:bg-emerald-800"
        >
          🛒 One-Click: Auto-Add All {plan.orders.length} Order{plan.orders.length === 1 ? '' : 's'} to Portal Carts
        </button>
      </div>

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
        <OrderCard key={i} order={o} dealById={dealById} extReady={extReady} onStatus={onStatus} />
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

export function OrderCard({
  order,
  dealById,
  extReady = false,
  onStatus,
}: {
  order: OrderOut
  dealById?: Map<string, Deal>
  extReady?: boolean
  onStatus?: (msg: string) => void
}) {
  const meta = PLATFORM_META[order.platform]
  const pending = order.status === 'pending'
  const [cartResults, setCartResults] = useState<CartItemResult[]>([])
  const [isAdding, setIsAdding] = useState(false)

  async function handleAddOrderToCart() {
    const items = buildCartItemsFromOrder(order, dealById)
    setIsAdding(true)
    try {
      const results = await triggerAddToCart(items, extReady, onStatus)
      setCartResults(results)
    } finally {
      setIsAdding(false)
    }
  }

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
        {order.lines.map((l) => {
          const itemUrl = l.url || dealById?.get(l.listing_id)?.url
          return (
            <li key={l.line_id} className="flex justify-between gap-2">
              <span className="min-w-0 truncate">
                {l.is_filler && <span className="mr-1 rounded bg-slate-100 px-1 text-[10px] font-bold uppercase">filler</span>}
                {itemUrl ? (
                  <a href={itemUrl} target="_blank" rel="noopener noreferrer" className="underline decoration-slate-300 hover:text-orange-700">
                    {l.title} ↗
                  </a>
                ) : (
                  l.title
                )}{' '}
                <span className="text-slate-400">
                  {l.packs > 1 ? `${l.packs} × ` : ''}
                  {l.pack_label}
                </span>
              </span>
              <span className="shrink-0 font-semibold">{formatINR(l.line_total_paise)}</span>
            </li>
          )
        })}
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
      <button
        type="button"
        disabled={isAdding}
        onClick={handleAddOrderToCart}
        className="mt-3 w-full rounded-xl border border-slate-300 bg-slate-50 py-2 text-xs font-bold text-slate-900 hover:bg-slate-100 disabled:opacity-50"
      >
        {isAdding ? `Adding to ${meta.name} cart…` : `Add to ${meta.name} cart`}
      </button>

      {cartResults.length > 0 && (
        <ul className="mt-2 space-y-1 rounded-xl bg-slate-50 p-2 text-xs">
          {cartResults.map((res, idx) => (
            <li key={idx} className="flex items-center justify-between gap-2">
              <span className="truncate text-slate-700">{res.title}</span>
              <span
                className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${
                  res.status === 'added'
                    ? 'bg-emerald-100 text-emerald-800'
                    : res.status === 'opened for you'
                      ? 'bg-sky-100 text-sky-800'
                      : 'bg-rose-100 text-rose-800'
                }`}
              >
                {res.status}
              </span>
            </li>
          ))}
        </ul>
      )}
    </article>
  )
}
