/* eslint-disable react-refresh/only-export-components */
import { useEffect, useMemo, useState } from 'react'
import {
  catalog,
  PLATFORM_META,
  PLATFORMS,
  type CatalogCandidate,
  type CatalogProductItem,
  type CatalogSearchUrl,
  type NewListing,
  type NoLinkShop,
  type Platform,
  type RawCandidateIn,
} from '../../lib/api'
import { formatINR } from '../../lib/money'
import { Card, ErrorNote, SectionTitle } from '../../lib/ui'

const CATEGORY_VOCAB_MAP: Record<string, string> = {
  'dry fruits & nuts': 'dryfruits',
  'dry fruits and nuts': 'dryfruits',
  dry_fruits_nuts: 'dryfruits',
  dry_fruits: 'dryfruits',
  almonds: 'dryfruits',
  cashews: 'dryfruits',
  raisins: 'dryfruits',
  walnuts: 'dryfruits',
  dryfruits: 'dryfruits',
  'dal & pulses': 'staples',
  'dal and pulses': 'staples',
  dal_pulses: 'staples',
  'rice, grains & flours': 'staples',
  'rice, grains and flours': 'staples',
  rice_grains_flours: 'staples',
  'spices & masalas': 'staples',
  'spices and masalas': 'staples',
  spices_masalas: 'staples',
  'cooking essentials': 'staples',
  cooking_essentials: 'staples',
  'packaged ready mixes': 'staples',
  packaged_ready_mixes: 'staples',
  staples: 'staples',
  'breakfast & cereals': 'breakfast',
  'breakfast and cereals': 'breakfast',
  breakfast_cereals: 'breakfast',
  breakfast: 'breakfast',
  'snacks & savoury': 'snacks',
  'snacks and savoury': 'snacks',
  'snacks & savory': 'snacks',
  'snacks and savory': 'snacks',
  snacks_savoury: 'snacks',
  snacks_savory: 'snacks',
  snacks: 'snacks',
  dairy: 'dairy',
  fitness: 'fitness',
  bakery: 'bakery',
  poultry: 'poultry',
  spices: 'spices',
}

export function categoryToSlug(category: string): string {
  const s = category.toLowerCase().trim()
  return (
    CATEGORY_VOCAB_MAP[s] ||
    s.replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '').slice(0, 30) ||
    'staples'
  )
}

export function isValidPack(val: string): boolean {
  const trimmed = val.trim()
  if (!trimmed) return false
  // Whole numbers for g/ml/pieces; kg and litres may have decimals (0.5kg = 500g), as the server's parse_pack accepts.
  return (
    /^\d+\s*(?:g|gm|gms|gram|grams|ml|mls|pcs|pieces|pc)$/i.test(trimmed) ||
    /^\d+(?:\.\d+)?\s*(?:kg|kgs|l|ltr|ltrs|litre|litres)$/i.test(trimmed)
  )
}

export function groupCandidatesByPlatform(
  candidates: CatalogCandidate[],
): Map<Platform, CatalogCandidate[]> {
  const grouped = new Map<Platform, CatalogCandidate[]>()
  for (const p of PLATFORMS) {
    grouped.set(p, [])
  }
  for (const c of candidates) {
    const list = grouped.get(c.platform)
    if (list) {
      list.push(c)
    } else {
      grouped.set(c.platform, [c])
    }
  }
  return grouped
}

export interface TrackDeps {
  addListing?: (l: NewListing) => Promise<{ listing_id: string; product_key: string }>
  existingByUrl?: Map<string, string>
}

export async function trackSelectedCandidates(
  product: CatalogProductItem,
  selectedCandidates: CatalogCandidate[],
  deps?: TrackDeps,
): Promise<string[]> {
  const addFn = deps?.addListing ?? catalog.addListing
  let urlMap = deps?.existingByUrl
  if (!urlMap) {
    try {
      const existing = await catalog.listings()
      urlMap = new Map(existing.map((e) => [e.url, e.listing_id]))
    } catch {
      urlMap = new Map()
    }
  }

  const trackedIds: string[] = []
  const categorySlug = categoryToSlug(product.category)

  for (const c of selectedCandidates) {
    const existingId = c.existing_listing_id || urlMap.get(c.url)
    if (existingId) {
      trackedIds.push(existingId)
      continue
    }

    const price = c.price_paise && c.price_paise > 0 ? c.price_paise : 100
    const brand = (c.brand || product.brand || 'Generic').slice(0, 40)
    const packLabel = c.pack_label || ''
    const created = await addFn({
      url: c.url,
      title: c.title.slice(0, 120),
      brand,
      pack_label: packLabel,
      category: categorySlug,
      family_key: product.family_key,
      listed_paise: price,
      mrp_paise: price,
      member_price_paise: null,
      in_stock: true,
    })
    urlMap.set(c.url, created.listing_id)
    trackedIds.push(created.listing_id)
  }

  return trackedIds
}

export default function FindOnShops({
  product,
  extReady,
  initialSearchUrls,
  initialCandidates,
  initialNoLinkShops,
  onClose,
  onTracked,
}: {
  product: CatalogProductItem
  extReady: boolean
  initialSearchUrls?: CatalogSearchUrl[]
  initialCandidates?: CatalogCandidate[]
  initialNoLinkShops?: NoLinkShop[]
  onClose: () => void
  onTracked?: (listingIds: string[]) => void
}) {
  const [searchUrls, setSearchUrls] = useState<CatalogSearchUrl[]>(initialSearchUrls ?? [])
  const [candidates, setCandidates] = useState<CatalogCandidate[]>(initialCandidates ?? [])
  const [noLinkShops, setNoLinkShops] = useState<NoLinkShop[]>(initialNoLinkShops ?? [])
  const [customPacks, setCustomPacks] = useState<Record<string, string>>({})
  const [selectedUrls, setSelectedUrls] = useState<Set<string>>(() => new Set())
  const [progressNote, setProgressNote] = useState<string | null>(null)
  const [searching, setSearching] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (initialSearchUrls && initialSearchUrls.length > 0) return
    let active = true
    const queryText = `${product.name} ${product.pack_label}`.trim()
    const fetchUrls =
      product.id <= 0
        ? catalog.searchUrlsFreeText(queryText)
        : catalog.searchUrls(product.id)

    fetchUrls
      .then((urls) => {
        if (active) setSearchUrls(urls)
      })
      .catch((e) => {
        if (active) setError((e as Error).message)
      })
    return () => {
      active = false
    }
  }, [product.id, product.name, product.pack_label, initialSearchUrls])

  useEffect(() => {
    if (!extReady || initialCandidates !== undefined || searchUrls.length === 0) return
    let active = true
    setSearching(true)
    setProgressNote('Starting shop search…')

    function onMessage(e: MessageEvent) {
      if (!active || e.source !== window || !e.data || typeof e.data.type !== 'string') return
      if (e.data.catalogId !== undefined && e.data.catalogId !== product.id) return

      if (e.data.type === 'DEALSCOUR_FIND_PROGRESS') {
        const { platform, found } = e.data as { platform: Platform; found: number }
        const shopName = PLATFORM_META[platform]?.name ?? platform
        setProgressNote(`Searching ${shopName}… ${found} found`)
      } else if (e.data.type === 'DEALSCOUR_FIND_COMPLETE') {
        const rawResults = (e.data.results as (RawCandidateIn | NoLinkShop)[]) ?? []
        const noLinks = rawResults.filter((r): r is NoLinkShop => 'status' in r && r.status === 'no_links')
        if (noLinks.length > 0) {
          setNoLinkShops((prev) => {
            const existingPlatforms = new Set(prev.map((s) => s.platform))
            const newShops = noLinks.filter((s) => !existingPlatforms.has(s.platform))
            return [...prev, ...newShops]
          })
        }
        const validCandidates = rawResults.filter(
          (r): r is RawCandidateIn => !('status' in r) && Boolean(r.url),
        )

        setProgressNote('Scoring candidates…')
        const queryText = `${product.name} ${product.pack_label}`.trim()
        const scorePromise =
          product.id <= 0
            ? catalog.scoreCandidatesFreeText(
                queryText,
                product.pack_label,
                validCandidates.slice(0, 25),
              )
            : catalog.scoreCandidates(product.id, validCandidates.slice(0, 25))

        scorePromise
          .then((scored) => {
            if (!active) return
            setCandidates(scored)
            setSearching(false)
            setProgressNote(null)
          })
          .catch((err) => {
            if (!active) return
            setError((err as Error).message)
            setSearching(false)
            setProgressNote(null)
          })
      } else if (e.data.type === 'DEALSCOUR_FIND_ERROR') {
        setError(String(e.data.error ?? 'Extension search failed'))
        setSearching(false)
        setProgressNote(null)
      }
    }

    window.addEventListener('message', onMessage)
    window.postMessage(
      {
        type: 'DEALSCOUR_FIND_PRODUCT',
        catalogId: product.id,
        targets: searchUrls,
      },
      window.location.origin,
    )

    return () => {
      active = false
      window.removeEventListener('message', onMessage)
    }
  }, [extReady, initialCandidates, product.id, product.name, product.pack_label, searchUrls])

  const grouped = useMemo(() => groupCandidatesByPlatform(candidates), [candidates])

  function toggleUrl(url: string) {
    setSelectedUrls((prev) => {
      const next = new Set(prev)
      if (next.has(url)) {
        next.delete(url)
      } else {
        next.add(url)
      }
      return next
    })
  }

  async function handleTrackSelected() {
    const chosen = candidates
      .filter((c) => selectedUrls.has(c.url))
      .map((c) => ({
        ...c,
        pack_label: c.pack_label || customPacks[c.url] || '',
      }))
    if (chosen.length === 0) return
    setSaving(true)
    setError(null)
    try {
      const ids = await trackSelectedCandidates(product, chosen)
      onTracked?.(ids)
      onClose()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card>
      <div className="flex items-center justify-between gap-2">
        <div>
          <SectionTitle>Find on shops</SectionTitle>
          <p className="text-xs font-semibold text-slate-700">
            {product.name} · <span className="text-slate-500">{product.pack_label}</span>
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg px-2 py-1 text-xs font-bold text-slate-500 hover:bg-slate-100"
        >
          Close ✕
        </button>
      </div>

      <ErrorNote error={error} />

      {!extReady ? (
        <div className="mt-3 space-y-2.5 rounded-xl border border-amber-200 bg-amber-50/70 p-3 text-xs">
          <p className="font-semibold text-amber-900">
            Install the DealScour extension to search shops
          </p>
          <div className="flex flex-wrap gap-2">
            {searchUrls.map((s) => (
              <a
                key={s.platform}
                href={s.url}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 font-semibold text-slate-800 hover:bg-slate-50"
              >
                {PLATFORM_META[s.platform]?.name ?? s.platform} ↗
              </a>
            ))}
          </div>
        </div>
      ) : (
        <div className="mt-3 space-y-3">
          {progressNote && (
            <p className="rounded-xl bg-slate-100 px-3 py-2 text-xs font-medium text-slate-700">
              {progressNote}
            </p>
          )}

          {!searching && candidates.length === 0 && noLinkShops.length === 0 && (
            <p className="text-xs text-slate-500">No product candidates found across shops yet.</p>
          )}

          {noLinkShops.length > 0 && (
            <div className="space-y-2">
              {noLinkShops.map((shop) => {
                const shopName = PLATFORM_META[shop.platform]?.name ?? shop.platform
                if (shop.platform === 'blinkit' || shop.platform === 'instamart') {
                  return (
                    <div
                      key={shop.platform}
                      className="rounded-xl border border-amber-200 bg-amber-50/70 p-3 text-xs text-amber-900"
                    >
                      {shopName}: no product links on its search page.{' '}
                      <a
                        href={shop.search_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="font-bold underline decoration-amber-400"
                      >
                        Open search on {shopName} ↗
                      </a>
                      , open the right product and paste its link in Prices → Add a product.
                    </div>
                  )
                }
                return (
                  <div
                    key={shop.platform}
                    className="flex items-center justify-between gap-2 rounded-xl border border-slate-200 bg-slate-50 p-2.5 text-xs text-slate-700"
                  >
                    <span>No results on {shopName}.</span>
                    <a
                      href={shop.search_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-semibold text-orange-700 underline decoration-orange-300"
                    >
                      Open search ↗
                    </a>
                  </div>
                )
              })}
            </div>
          )}

          {PLATFORMS.map((plat) => {
            const list = grouped.get(plat) ?? []
            if (list.length === 0) return null
            const meta = PLATFORM_META[plat]
            return (
              <div key={plat} className="space-y-1.5">
                <div className="flex items-center gap-1.5 text-xs font-bold text-slate-700">
                  <span
                    className="h-2 w-2 rounded-full"
                    style={{ backgroundColor: meta.color }}
                  />
                  <span>{meta.name}</span>
                </div>
                <ul className="space-y-1.5">
                  {list.map((c) => {
                    const checked = selectedUrls.has(c.url)
                    const typedPack = customPacks[c.url] ?? ''
                    const hasValidPack = c.pack_label ? true : isValidPack(typedPack)
                    return (
                      <li
                        key={c.url}
                        className="flex items-center justify-between gap-2 rounded-xl border border-slate-200 bg-white p-2.5 text-xs"
                      >
                        <label className="flex min-w-0 flex-1 items-center gap-2 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={checked}
                            disabled={!hasValidPack}
                            onChange={() => toggleUrl(c.url)}
                          />
                          <span className="truncate font-medium text-slate-800">{c.title}</span>
                          {c.pack_label ? (
                            <span
                              className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-bold ${
                                c.pack_matches
                                  ? 'bg-emerald-100 text-emerald-800'
                                  : 'bg-slate-100 text-slate-600'
                              }`}
                            >
                              {c.pack_label}
                            </span>
                          ) : (
                            <input
                              type="text"
                              placeholder="e.g. 200g"
                              value={typedPack}
                              onClick={(e) => e.stopPropagation()}
                              onChange={(e) => {
                                const val = e.target.value
                                setCustomPacks((prev) => ({ ...prev, [c.url]: val }))
                                if (!isValidPack(val) && selectedUrls.has(c.url)) {
                                  setSelectedUrls((prev) => {
                                    const next = new Set(prev)
                                    next.delete(c.url)
                                    return next
                                  })
                                }
                              }}
                              className="w-20 shrink-0 rounded border border-slate-300 px-1.5 py-0.5 text-[11px] text-slate-800 focus:border-slate-500 focus:outline-none"
                            />
                          )}
                        </label>
                        <div className="flex shrink-0 items-center gap-2">
                          {c.price_paise != null && (
                            <span className="font-bold text-slate-900">
                              {formatINR(c.price_paise)}
                            </span>
                          )}
                          <a
                            href={c.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="font-semibold text-orange-700 underline decoration-orange-300"
                          >
                            Open ↗
                          </a>
                        </div>
                      </li>
                    )
                  })}
                </ul>
              </div>
            )
          })}

          <button
            type="button"
            disabled={saving || selectedUrls.size === 0}
            onClick={() => void handleTrackSelected()}
            className="w-full rounded-xl bg-slate-900 py-2.5 text-xs font-bold text-white hover:bg-slate-800 disabled:opacity-40"
          >
            {saving ? 'Tracking…' : 'Track selected'}
          </button>
        </div>
      )}
    </Card>
  )
}
