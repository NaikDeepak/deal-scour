import type { Basket, Deal, OrderOut, Platform } from '../../lib/api'

export interface CartTargetItem {
  listing_id: string
  title: string
  packs: number
  platform: Platform
  url: string
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
    }
  })
}

export function triggerAddToCart(
  items: CartTargetItem[],
  extReady: boolean,
  onStatus?: (msg: string) => void,
): void {
  if (items.length === 0) return

  if (extReady && typeof window !== 'undefined') {
    onStatus?.(`Auto-adding ${items.length} item(s) to cart via DealScour Extension…`)
    window.postMessage(
      {
        type: 'DEALSCOUR_ADD_TO_CART_REQUEST',
        items,
      },
      window.location.origin,
    )
    return
  }

  // Fallback when extension is not installed: launch each item's URL in a new tab
  onStatus?.(`Opened ${items.length} item tab(s). Load the extension/ folder in Chrome to auto-click Add to Cart!`)
  for (const item of items) {
    window.open(item.url, '_blank', 'noopener,noreferrer')
  }
}
