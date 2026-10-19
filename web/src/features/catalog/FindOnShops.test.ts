import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import type { CatalogCandidate, CatalogProductItem, CatalogSearchUrl } from '../../lib/api'
import FindOnShops, { groupCandidatesByPlatform, isValidPack, trackSelectedCandidates } from './FindOnShops'

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
      category: 'staples',
      family_key: 'toor_dal',
      listed_paise: 14000,
      mrp_paise: 14000,
      member_price_paise: null,
      in_stock: true,
    })
  })

  it('renders "Open search on Blinkit ↗" for a no_links shop', () => {
    const html = renderToStaticMarkup(
      createElement(FindOnShops, {
        product: PRODUCT,
        extReady: true,
        initialSearchUrls: SEARCH_URLS,
        initialNoLinkShops: [
          {
            platform: 'blinkit',
            status: 'no_links',
            search_url: 'https://blinkit.com/s/?q=Tata+Sampann+Toor+Dal+600g',
          },
        ],
        onClose: () => {},
      }),
    )
    expect(html).toContain('Open search on Blinkit ↗')
    expect(html).toContain('no product links on its search page')
  })

  it('candidate with null pack_label renders pack input and disables checkbox until typed', () => {
    const candidateNoPack: CatalogCandidate = {
      platform: 'flipkart',
      sku: 'WAL12345678',
      url: 'https://www.flipkart.com/walnuts/p/itm123456?pid=WAL12345678',
      title: 'Flipkart Walnuts',
      price_paise: 25000,
      pack_label: null,
      pack_matches: false,
      score: 1,
    }
    const html = renderToStaticMarkup(
      createElement(FindOnShops, {
        product: { ...PRODUCT, pack_label: '500g' },
        extReady: true,
        initialSearchUrls: SEARCH_URLS,
        initialCandidates: [candidateNoPack],
        onClose: () => {},
      }),
    )
    expect(html).toContain('placeholder="e.g. 200g"')
    expect(html).toContain('disabled=""')
  })

  it('uses candidate brand instead of catalog brand when candidate has its own brand', async () => {
    const addListing = vi.fn().mockResolvedValue({ listing_id: 'cus-1', product_key: 'deluxe_walnuts' })
    const candidate: CatalogCandidate = {
      platform: 'amazon',
      sku: 'B000000001',
      url: 'https://www.amazon.in/dp/B000000001',
      title: 'Deluxe Walnut Kernels 200g',
      brand: 'Deluxe',
      price_paise: 25000,
      pack_label: '200g',
      pack_matches: false,
      score: 2,
    }
    await trackSelectedCandidates(
      { ...PRODUCT, brand: 'Happilo' },
      [candidate],
      { addListing, existingByUrl: new Map() },
    )
    expect(addListing).toHaveBeenCalledWith(
      expect.objectContaining({
        brand: 'Deluxe',
        pack_label: '200g',
      }),
    )
  })
})

describe('isValidPack', () => {
  it('accepts packs the server can parse and rejects the rest', () => {
    for (const ok of ['200g', '200 g', '500gm', '1kg', '0.5kg', '1.5 l', '6 pcs', '750ml']) expect(isValidPack(ok)).toBe(true)
    for (const bad of ['', '0.5g', '2.5ml', 'g', 'about 200g', '200']) expect(isValidPack(bad)).toBe(false)
  })
})
