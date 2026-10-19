import { describe, expect, it } from 'vitest'
import type { Deal, OrderOut } from '../../lib/api'
import { buildCartItemsFromOrder, fallbackSearchUrl } from './cartBuilder'

describe('buildCartItemsFromOrder', () => {
  it('extracts cart items with line.url, dealById url, or platform search fallback', () => {
    const order: OrderOut = {
      platform: 'flipkart',
      status: 'now',
      subtotal_paise: 95000,
      fees: { delivery: 0, handling: 0, platform: 0, small_cart: 0, surge: 0, total: 0 },
      offers_applied: [{ offer_id: 'FK75', face_value_paise: 7500, effective_value_paise: 7500 }],
      net_paise: 87500,
      shortfall_paise: null,
      target_offer_id: null,
      lines: [
        {
          line_id: 'Cashews 500g',
          listing_id: 'cas-flipkart-500g',
          title: 'Nutraj Whole Cashews W320 Pouch',
          pack_label: '500g',
          packs: 1,
          unit_price_paise: 46000,
          line_total_paise: 46000,
          is_filler: false,
          url: 'https://www.flipkart.com/search?q=nutraj+cashews+500g',
        },
        {
          line_id: 'Walnuts 500g',
          listing_id: 'wal-1',
          title: 'Nutraj Kashmir Snow White Walnut Kernels',
          pack_label: '500g',
          packs: 2,
          unit_price_paise: 49000,
          line_total_paise: 98000,
          is_filler: false,
        },
      ],
    }

    const dealById = new Map<string, Deal>()
    const items = buildCartItemsFromOrder(order, dealById)
    expect(items).toHaveLength(2)
    expect(items[0]).toEqual({
      listing_id: 'cas-flipkart-500g',
      title: 'Nutraj Whole Cashews W320 Pouch',
      packs: 1,
      platform: 'flipkart',
      url: 'https://www.flipkart.com/search?q=nutraj+cashews+500g',
    })
    expect(items[1].packs).toBe(2)
    expect(items[1].url).toBe(fallbackSearchUrl('flipkart', 'Nutraj Kashmir Snow White Walnut Kernels 500g'))
  })
})
