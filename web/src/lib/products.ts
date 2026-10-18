import { useEffect, useMemo, useState } from 'react'
import { fetchDeals, type Deal, type Platform } from './api'

export interface Product {
  key: string
  family: string
  title: string
  brand: string
  pack: string
  icon: string
  best: Deal
}

export function useProducts(members: Platform[]) {
  const [deals, setDeals] = useState<Deal[]>([])
  useEffect(() => {
    fetchDeals(members)
      .then((r) => setDeals(r.deals))
      .catch(() => setDeals([]))
  }, [members])
  const products = useMemo(() => {
    const byKey = new Map<string, Product>()
    for (const d of deals) {
      const p = byKey.get(d.product_key)
      if (!p || d.unit_price_paise < p.best.unit_price_paise) {
        byKey.set(d.product_key, { key: d.product_key, family: d.family_key, title: d.title, brand: d.brand, pack: d.pack_label, icon: d.icon, best: d })
      }
    }
    return [...byKey.values()].sort((a, b) => a.brand.localeCompare(b.brand))
  }, [deals])
  return { deals, products }
}
