/* eslint-disable react-refresh/only-export-components */
import { useEffect, useState } from 'react'
import {
  catalog,
  type CatalogProductItem,
  type NeedIn,
  type SavedNeed,
} from '../../lib/api'
import { formatINR } from '../../lib/money'
import type { Product } from '../../lib/products'
import { inputClass } from '../../lib/ui'
import FindOnShops from '../catalog/FindOnShops'

export function catalogProductToNeed(
  item: CatalogProductItem,
): Omit<NeedIn, 'line_id'> & { line_id: string } {
  return {
    line_id: `${item.name} ${item.pack_label}`,
    product_key: null,
    family_key: item.family_key,
    quantity: item.pack_label,
    qty: 1,
    need_by_minutes: null,
    lock_platform: null,
  }
}

export async function searchCatalogItems(
  rawQuery: string,
  searchFn: (q: string, limit?: number) => Promise<CatalogProductItem[]> = catalog.search,
): Promise<CatalogProductItem[]> {
  const trimmed = rawQuery.trim()
  if (!trimmed) return []
  const res = await searchFn(trimmed, 8)
  return res.slice(0, 8)
}

export function CatalogResultsSection({
  items,
  onPickCatalog,
  onFindOnShops,
}: {
  items: CatalogProductItem[]
  onPickCatalog: (item: CatalogProductItem) => void
  onFindOnShops: (item: CatalogProductItem) => void
}) {
  const visible = items.slice(0, 8)
  if (visible.length === 0) return null

  return (
    <div className="mt-2 rounded-xl border border-slate-200 bg-white p-2.5 shadow-xs">
      <div className="px-1 pb-1.5 text-[11px] font-bold uppercase tracking-wide text-slate-500">
        From your catalog
      </div>
      <ul className="divide-y divide-slate-100">
        {visible.map((item) => (
          <li key={item.id} className="flex items-center justify-between gap-2 py-1.5 text-xs">
            <button
              type="button"
              onClick={() => onPickCatalog(item)}
              className="min-w-0 flex-1 truncate text-left font-semibold text-slate-800 hover:text-orange-700"
            >
              {item.name} <span className="font-normal text-slate-500">{item.pack_label}</span>
            </button>
            <button
              type="button"
              onClick={() => onFindOnShops(item)}
              className="shrink-0 rounded-lg border border-orange-200 bg-orange-50 px-2 py-1 text-[11px] font-bold text-orange-800 hover:bg-orange-100"
            >
              Find on shops
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function CatalogNeedFindButton({
  need,
  catalogItem,
  onFindOnShops,
}: {
  need: SavedNeed
  catalogItem?: CatalogProductItem | null
  onFindOnShops: (item: CatalogProductItem) => void
}) {
  async function handleClick() {
    if (catalogItem) {
      onFindOnShops(catalogItem)
      return
    }
    const queryText =
      need.quantity && need.line_id.endsWith(` ${need.quantity}`)
        ? need.line_id.slice(0, -(need.quantity.length + 1)).trim()
        : need.line_id
    let exact: CatalogProductItem | undefined
    try {
      const results = await catalog.search(queryText, 5)
      // Only an exact name + pack match; never guess another product.
      exact = results.find((r) => `${r.name} ${r.pack_label}` === need.line_id)
    } catch {
      // Ignore network errors
    }
    if (exact) {
      onFindOnShops(exact)
    } else {
      onFindOnShops({
        id: 0,
        seed_product_id: '',
        name: queryText || need.line_id,
        brand: '',
        category: 'staples',
        family_key: need.family_key || '',
        pack_label: need.quantity || '',
        target_pack_weight_g: 0,
        suggestions: [],
      })
    }
  }

  return (
    <button
      type="button"
      onClick={() => void handleClick()}
      className="rounded border border-orange-200 bg-orange-50 px-2 py-0.5 text-xs font-semibold text-orange-800 hover:bg-orange-100"
    >
      Find on shops
    </button>
  )
}

export default function CatalogPicker({
  products = [],
  placeholder = 'Add an item…',
  extReady = false,
  initialQuery = '',
  initialCatalogItems = [],
  onPickProduct,
  onPickCatalogNeed,
  onFindOnShops,
  onTrackedListings,
}: {
  products?: Product[]
  placeholder?: string
  extReady?: boolean
  initialQuery?: string
  initialCatalogItems?: CatalogProductItem[]
  onPickProduct?: (productKey: string) => void
  onPickCatalogNeed?: (
    need: Omit<NeedIn, 'line_id'> & { line_id: string },
    item: CatalogProductItem,
  ) => void
  onFindOnShops?: (item: CatalogProductItem) => void
  onTrackedListings?: (listingIds: string[]) => void
}) {
  const [query, setQuery] = useState(initialQuery)
  const [catalogItems, setCatalogItems] = useState<CatalogProductItem[]>(initialCatalogItems)
  const [findingProduct, setFindingProduct] = useState<CatalogProductItem | null>(null)

  useEffect(() => {
    const trimmed = query.trim()
    if (!trimmed) {
      setCatalogItems([])
      return
    }
    let active = true
    const timer = setTimeout(() => {
      searchCatalogItems(trimmed)
        .then((res) => {
          if (active) setCatalogItems(res)
        })
        .catch(() => {
          if (active) setCatalogItems([])
        })
    }, 250)
    return () => {
      active = false
      clearTimeout(timer)
    }
  }, [query])

  function handleFind(item: CatalogProductItem) {
    if (onFindOnShops) {
      onFindOnShops(item)
    } else {
      setFindingProduct(item)
    }
  }

  return (
    <div className="mt-2 space-y-2">
      <input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder={placeholder}
        className={inputClass}
      />

      {products.length > 0 && (
        <select
          value=""
          onChange={(e) => e.target.value && onPickProduct?.(e.target.value)}
          className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"
        >
          <option value="">{placeholder}</option>
          {products.map((p) => (
            <option key={p.key} value={p.key}>
              {p.icon} {p.brand} {p.pack}, from {formatINR(p.best.unit_price_paise)}
            </option>
          ))}
        </select>
      )}

      <CatalogResultsSection
        items={catalogItems}
        onPickCatalog={(item) => {
          onPickCatalogNeed?.(catalogProductToNeed(item), item)
          setQuery('')
          setCatalogItems([])
        }}
        onFindOnShops={handleFind}
      />

      {findingProduct && (
        <FindOnShops
          product={findingProduct}
          extReady={extReady}
          onClose={() => setFindingProduct(null)}
          onTracked={(ids) => onTrackedListings?.(ids)}
        />
      )}
    </div>
  )
}
