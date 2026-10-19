import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import type { CatalogCandidate, CatalogProductItem, CatalogSearchUrl } from '../../lib/api'
import FindOnShops, { groupCandidatesByPlatform, trackSelectedCandidates } from './FindOnShops'

const PRODUCT: CatalogProductItem = {
  id: 1,
  seed_product_id: 'DS-0001',
  name: 'Tata Sampann Toor/Arhar Dal',
  brand: 'Tata Sampann',
  category: 'Dal & Pulses',
  family_key: 'toor_dal',
  pack_label: '600g',
  target_pack_weight_g: 600,
  suggestions: [],
}

const SEARCH_URLS: CatalogSearchUrl[] = [
  { platform: 'amazon', url: 'https://www.amazon.in/s?k=Tata+Sampann+Toor+Dal+600g' },
  { platform: 'flipkart', url: 'https://www.flipkart.com/search?q=Tata+Sampann+Toor+Dal+600g' },
  { platform: 'blinkit', url: 'https://blinkit.com/s/?q=Tata+Sampann+Toor+Dal+600g' },
  { platform: 'zepto', url: 'https://www.zepto.com/search?query=Tata+Sampann+Toor+Dal+600g' },
  { platform: 'instamart', url: 'https://www.swiggy.com/instamart/search?query=Tata+Sampann+Toor+Dal+600g' },
]

describe('FindOnShops', () => {
  it('shows the no-extension fallback and plain search links per shop when extension is not installed', () => {
    const html = renderToStaticMarkup(
      createElement(FindOnShops, {
        product: PRODUCT,
        extReady: false,
        initialSearchUrls: SEARCH_URLS,
        onClose: () => {},
        onTracked: () => {},
      }),
    )

    expect(html).toContain('Install the DealScour extension to search shops')
    expect(html).toContain('https://www.amazon.in/s?k=Tata+Sampann+Toor+Dal+600g')
    expect(html).toContain('https://www.flipkart.com/search?q=Tata+Sampann+Toor+Dal+600g')
    expect(html).toContain('https://blinkit.com/s/?q=Tata+Sampann+Toor+Dal+600g')
    expect(html).toContain('https://www.zepto.com/search?query=Tata+Sampann+Toor+Dal+600g')
    expect(html).toContain('https://www.swiggy.com/instamart/search?query=Tata+Sampann+Toor+Dal+600g')
  })

  it('groups candidates by shop and renders green pack badge when pack_matches is true', () => {
    const candidates: CatalogCandidate[] = [
      {
        platform: 'amazon',
        sku: 'B07BG5M32L',
        url: 'https://www.amazon.in/dp/B07BG5M32L',
        title: 'Tata Sampann Unpolished Toor Dal',
        price_paise: 13500,
        pack_label: '600g',
        pack_matches: true,
        score: 6,
      },
      {
        platform: 'flipkart',
        sku: 'DAL12345678',
        url: 'https://www.flipkart.com/toor-dal/p/itm123456?pid=DAL12345678',
        title: 'Other Toor Dal 1kg',
        price_paise: 18500,
        pack_label: '1kg',
        pack_matches: false,
        score: 2,
      },
    ]

    const grouped = groupCandidatesByPlatform(candidates)
    expect(grouped.get('amazon')).toHaveLength(1)
    expect(grouped.get('flipkart')).toHaveLength(1)

    const html = renderToStaticMarkup(
      createElement(FindOnShops, {
        product: PRODUCT,
        extReady: true,
        initialSearchUrls: SEARCH_URLS,
        initialCandidates: candidates,
        onClose: () => {},
        onTracked: () => {},
      }),
    )

    expect(html).toContain('Tata Sampann Unpolished Toor Dal')
    expect(html).toContain('text-emerald-800')
    expect(html).toContain('Open ↗')
    expect(html).toContain('Track selected')
  })

  it('reuses existing listing with same canonical URL instead of creating a duplicate', async () => {
    const addListing = vi.fn().mockResolvedValue({ listing_id: 'cus-99', product_key: 'tata_dal' })
    const candidates: CatalogCandidate[] = [
      {
        platform: 'amazon',
        sku: 'B07BG5M32L',
        url: 'https://www.amazon.in/dp/B07BG5M32L',
        title: 'Tata Sampann Unpolished Toor Dal',
        price_paise: 13500,
        pack_label: '600g',
        pack_matches: true,
        score: 6,
        existing_listing_id: 'cus-10',
      },
      {
        platform: 'flipkart',
        sku: 'DAL12345678',
        url: 'https://www.flipkart.com/toor-dal/p/itm123456?pid=DAL12345678',
        title: 'Tata Sampann Toor Dal',
        price_paise: 14000,
        pack_label: '600g',
        pack_matches: true,
        score: 6,
        existing_listing_id: null,
      },
    ]

    const tracked = await trackSelectedCandidates(PRODUCT, candidates, {
      addListing,
      existingByUrl: new Map([['https://www.amazon.in/dp/B07BG5M32L', 'cus-10']]),
    })

    expect(tracked).toEqual(['cus-10', 'cus-99'])
    expect(addListing).toHaveBeenCalledTimes(1)
    expect(addListing).toHaveBeenCalledWith({
      url: 'https://www.flipkart.com/toor-dal/p/itm123456?pid=DAL12345678',
      title: 'Tata Sampann Toor Dal',
      brand: 'Tata Sampann',
      pack_label: '600g',
      category: 'dal_pulses',
      family_key: 'toor_dal',
      listed_paise: 14000,
      mrp_paise: 14000,
      member_price_paise: null,
      in_stock: true,
    })
  })
})
