import { describe, expect, it } from 'vitest'
import type { Deal, OrderOut } from '../../lib/api'
import { buildCartItemsFromOrder, categorizeCartResult, fallbackSearchUrl, processPriceCaptures } from './cartBuilder'

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
      autoClick: false,
    })
    expect(items[1].packs).toBe(2)
    expect(items[1].url).toBe(fallbackSearchUrl('flipkart', 'Nutraj Kashmir Snow White Walnut Kernels 500g'))
    expect(items[1].autoClick).toBe(false)
  })

  it('flags search-url items with autoClick:false and product-url items with autoClick:true (Case 8)', () => {
    const order: OrderOut = {
      platform: 'amazon',
      status: 'now',
      subtotal_paise: 95000,
      fees: { delivery: 0, handling: 0, platform: 0, small_cart: 0, surge: 0, total: 0 },
      offers_applied: [],
      net_paise: 95000,
      shortfall_paise: null,
      target_offer_id: null,
      lines: [
        {
          line_id: 'item-1',
          listing_id: 'l-1',
          title: 'Product 1',
          pack_label: '500g',
          packs: 1,
          unit_price_paise: 50000,
          line_total_paise: 50000,
          is_filler: false,
          url: 'https://www.amazon.in/dp/B00EXAMPLE',
        },
        {
          line_id: 'item-2',
          listing_id: 'l-2',
          title: 'Search Item',
          pack_label: '500g',
          packs: 1,
          unit_price_paise: 45000,
          line_total_paise: 45000,
          is_filler: false,
          url: 'https://www.amazon.in/s?k=search+query',
        },
      ],
    }

    const items = buildCartItemsFromOrder(order)
    expect(items[0].autoClick).toBe(true)
    expect(items[1].autoClick).toBe(false)
  })
})

describe('categorizeCartResult', () => {
  it('categorizes added items as added', () => {
    expect(categorizeCartResult({ added: true })).toBe('added')
  })

  it('categorizes search-page and tab-open items as opened for you', () => {
    expect(categorizeCartResult({ added: false, reason: 'Search page: pick the product yourself' })).toBe('opened for you')
    expect(categorizeCartResult({ added: false, reason: 'Add-to-Cart button not found; tab left open for 1-click add' })).toBe('opened for you')
    expect(categorizeCartResult({ added: false, reason: 'Opened tab' })).toBe('opened for you')
  })

  it('categorizes other errors as failed', () => {
    expect(categorizeCartResult({ added: false, reason: 'Not a supported shop link' })).toBe('failed')
    expect(categorizeCartResult({ added: false, reason: 'Failed to open tab' })).toBe('failed')
    expect(categorizeCartResult({ added: false })).toBe('failed')
  })
})

describe('Case 19: processPriceCaptures (one 422 among three captures)', () => {
  it('saves two and lists the 422 capture for confirmation', async () => {
    const results = [
      { listing_id: 'l-1', ok: true, listed_paise: 50000 },
      { listing_id: 'l-2', ok: true, listed_paise: 20000 },
      { listing_id: 'l-3', ok: true, listed_paise: 48000 },
    ]

    const captured: string[] = []
    const mockCaptureFn = async (p: { listing_id?: string | null }) => {
      if (p.listing_id === 'l-2') {
        throw new Error('422: Price changed a lot. Check the page and confirm.')
      }
      if (p.listing_id) captured.push(p.listing_id)
      return { ok: true }
    }

    const batch = await processPriceCaptures(results, mockCaptureFn)
    expect(batch.savedCount).toBe(2)
    expect(captured).toEqual(['l-1', 'l-3'])
    expect(batch.pendingConfirmations).toHaveLength(1)
    expect(batch.pendingConfirmations[0].listing_id).toBe('l-2')
    expect(batch.pendingConfirmations[0].new_price_paise).toBe(20000)
  })
})
