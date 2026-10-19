import type { Basket, Deal, OrderOut, Platform } from '../../lib/api'

export interface CartTargetItem {
  listing_id: string
  title: string
  packs: number
  platform: Platform
  url: string
  autoClick: boolean
}

export interface CartItemResult {
  title: string
  status: 'added' | 'opened for you' | 'failed'
  detail?: string
}

export function isProductPageUrl(url: string): boolean {
  if (!url) return false
  try {
    const parsed = new URL(url)
    const path = parsed.pathname
    if (path.includes('/dp/') || path.includes('/gp/product/')) return true
    if (path.includes('/p/') && (parsed.searchParams.has('pid') || /\/p\/itm/i.test(path))) return true
    if (path.includes('/prid/')) return true
    if (path.includes('/pvid/')) return true
    if (path.includes('/instamart/item/')) return true
    return false
  } catch {
    return false
  }
}

export function categorizeCartResult(r: { added?: boolean; reason?: string }): 'added' | 'opened for you' | 'failed' {
  if (r.added) return 'added'
  const reason = (r.reason || '').toLowerCase()
  if (reason.includes('search page') || reason.includes('tab left open') || reason.includes('opened tab')) {
    return 'opened for you'
  }
  return 'failed'
}

export function fallbackSearchUrl(platform: Platform, query: string): string {
  const q = encodeURIComponent(query.trim())
  switch (platform) {
    case 'amazon':
      return `https://www.amazon.in/s?k=${q}`
    case 'flipkart':
      return `https://www.flipkart.com/search?q=${q}`
    case 'blinkit':
      return `https://blinkit.com/s/?q=${q}`
    case 'instamart':
      return `https://www.swiggy.com/instamart/search?custom_back=true&query=${q}`
    case 'zepto':
      return `https://www.zeptonow.com/search?query=${q}`
  }
}

export function buildCartItemsFromOrder(order: OrderOut, dealById?: Map<string, Deal>): CartTargetItem[] {
  return order.lines.map((line) => {
    const dealUrl = dealById?.get(line.listing_id)?.url
    const resolvedUrl = (line.url && line.url.trim()) || (dealUrl && dealUrl.trim()) || fallbackSearchUrl(order.platform, `${line.title} ${line.pack_label}`)
    return {
      listing_id: line.listing_id,
      title: line.title,
      packs: line.packs,
      platform: order.platform,
      url: resolvedUrl,
      autoClick: isProductPageUrl(resolvedUrl),
    }
  })
}

export function buildCartItemsFromBasket(basket: Basket, deals: Deal[]): CartTargetItem[] {
  const dealById = new Map(deals.map((d) => [d.id, d]))
  return basket.lines.map((line) => {
    const dealUrl = dealById.get(line.listing_id)?.url
    const resolvedUrl = (dealUrl && dealUrl.trim()) || fallbackSearchUrl(basket.platform, `${line.title} ${line.pack_label}`)
    return {
      listing_id: line.listing_id,
      title: line.title,
      packs: line.packs,
      platform: basket.platform,
      url: resolvedUrl,
      autoClick: isProductPageUrl(resolvedUrl),
    }
  })
}

export async function triggerAddToCart(
  items: CartTargetItem[],
  extReady: boolean,
  onStatus?: (msg: string) => void,
): Promise<CartItemResult[]> {
  if (items.length === 0) return []

  if (extReady && typeof window !== 'undefined') {
    onStatus?.(`Auto-adding ${items.length} item(s) to cart via DealScour Extension…`)
    return new Promise((resolve) => {
      const timeout = setTimeout(() => {
        window.removeEventListener('message', handler)
        resolve(
          items.map((it) => ({
            title: it.title,
            status: 'failed',
            detail: 'Extension timed out',
          })),
        )
      }, Math.max(20000, items.length * 15000))

      function handler(e: MessageEvent) {
        if (e.source !== window || !e.data || typeof e.data.type !== 'string') return
        if (e.data.type === 'DEALSCOUR_ADD_TO_CART_COMPLETE') {
          clearTimeout(timeout)
          window.removeEventListener('message', handler)
          const rawResults = (e.data.results as Array<{ title?: string; added?: boolean; reason?: string }>) ?? []
          const mapped: CartItemResult[] = items.map((item, idx) => {
            const raw = rawResults[idx] || rawResults.find((r) => r.title === item.title)
            if (!raw) return { title: item.title, status: 'failed', detail: 'No result returned' }
            const status = categorizeCartResult(raw)
            return { title: item.title, status, detail: raw.reason }
          })
          resolve(mapped)
        } else if (e.data.type === 'DEALSCOUR_ADD_TO_CART_ERROR') {
          clearTimeout(timeout)
          window.removeEventListener('message', handler)
          resolve(
            items.map((it) => ({
              title: it.title,
              status: 'failed',
              detail: String(e.data.error ?? 'Extension error'),
            })),
          )
        }
      }

      window.addEventListener('message', handler)
      window.postMessage(
        {
          type: 'DEALSCOUR_ADD_TO_CART_REQUEST',
          items,
        },
        window.location.origin,
      )
    })
  }

  // Fallback when extension is not installed: launch each item's URL in a new tab
  onStatus?.(`Opened ${items.length} item tab(s). Load the extension/ folder in Chrome to auto-click Add to Cart!`)
  for (const item of items) {
    window.open(item.url, '_blank', 'noopener,noreferrer')
  }
  return items.map((item) => ({
    title: item.title,
    status: 'opened for you',
    detail: 'Opened in a new tab',
  }))
}

export interface PriceConfirmationItem {
  listing_id: string
  title: string
  platform: Platform
  old_price_paise: number | null
  new_price_paise: number
  mrp_paise: number
  in_stock: boolean
  eta_minutes: number | null
}

export interface CaptureBatchResult {
  savedCount: number
  pendingConfirmations: PriceConfirmationItem[]
  errors: { listing_id: string; error: string }[]
}

export async function processPriceCaptures(
  results: Array<{
    listing_id: string
    ok: boolean
    listed_paise?: number
    mrp_paise?: number
    in_stock?: boolean
    eta_minutes?: number | null
  }>,
  captureFn: (payload: {
    listing_id: string
    listed_paise: number
    mrp_paise?: number | null
    in_stock?: boolean
    eta_minutes?: number | null
    confirm?: boolean
  }) => Promise<unknown>,
  targets?: Array<{ listing_id: string; title: string; platform: Platform }>,
  oldPriceByListingId?: Map<string, number>,
): Promise<CaptureBatchResult> {
  const targetMap = new Map((targets || []).map((t) => [t.listing_id, t]))
  const pendingConfirmations: PriceConfirmationItem[] = []
  const errors: { listing_id: string; error: string }[] = []
  let savedCount = 0

  for (const r of results) {
    if (!r.ok || !r.listed_paise || r.listed_paise <= 0) continue
    const target = targetMap.get(r.listing_id)
    const oldPrice = oldPriceByListingId?.get(r.listing_id) ?? null
    try {
      await captureFn({
        listing_id: r.listing_id,
        listed_paise: r.listed_paise,
        mrp_paise: r.mrp_paise ?? r.listed_paise,
        in_stock: r.in_stock ?? true,
        eta_minutes: r.eta_minutes ?? null,
      })
      savedCount += 1
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      if (msg.includes('Price changed a lot') || msg.includes('422')) {
        pendingConfirmations.push({
          listing_id: r.listing_id,
          title: target?.title ?? r.listing_id,
          platform: target?.platform ?? 'amazon',
          old_price_paise: oldPrice,
          new_price_paise: r.listed_paise,
          mrp_paise: r.mrp_paise ?? r.listed_paise,
          in_stock: r.in_stock ?? true,
          eta_minutes: r.eta_minutes ?? null,
        })
      } else {
        errors.push({ listing_id: r.listing_id, error: msg })
      }
    }
  }

  return { savedCount, pendingConfirmations, errors }
}
