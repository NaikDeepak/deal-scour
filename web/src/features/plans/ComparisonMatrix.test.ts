import { describe, expect, it } from 'vitest'
import type { Deal, SavedNeed } from '../../lib/api'
import { buildMatrixRows } from './matrixRows'

const SAMPLE_DEALS: Deal[] = [
  {
    id: 'stp-4',
    product_key: 'fortune_sunlite_oil_5l',
    family_key: 'sunflower_oil',
    category: 'staples',
    title: 'Fortune Sunlite Refined Sunflower Oil',
    brand: 'Fortune',
    platform: 'amazon',
    pack_label: '5L',
    icon: '🌻',
    url: 'https://www.amazon.in/dp/B01N5K32K0',
    unit_price_paise: 62900,
    unit_rate_paise: 12580,
    rate_basis_label: '1L',
    eta_minutes: 720,
    is_best_in_product: true,
    is_best_in_family: true,
    listed_paise: 64900,
    mrp_paise: 89000,
    price_source: 'extension',
    observed_at: '2026-10-19T08:00:00Z',
    freshness: 'fresh',
    in_stock: true,
  },
  {
    id: 'stp-5',
    product_key: 'fortune_sunlite_oil_5l',
    family_key: 'sunflower_oil',
    category: 'staples',
    title: 'Fortune Sunlite Refined Sunflower Oil',
    brand: 'Fortune',
    platform: 'flipkart',
    pack_label: '5L',
    icon: '🌻',
    url: 'https://www.flipkart.com/fortune-sunlite/p/itm123',
    unit_price_paise: 72500,
    unit_rate_paise: 14500,
    rate_basis_label: '1L',
    eta_minutes: 1440,
    is_best_in_product: false,
    is_best_in_family: false,
    listed_paise: 72500,
    mrp_paise: 89000,
    price_source: 'sample',
    observed_at: null,
    freshness: 'sample',
    in_stock: true,
  },
  {
    id: 'stp-1',
    product_key: 'aashirvaad_shudh_chakki_atta_5kg',
    family_key: 'atta',
    category: 'staples',
    title: 'Aashirvaad Shudh Chakki Atta',
    brand: 'Aashirvaad',
    platform: 'blinkit',
    pack_label: '5kg',
    icon: '🌾',
    url: 'https://blinkit.com/prn/aashirvaad-atta/prid/101',
    unit_price_paise: 24200,
    unit_rate_paise: 4840,
    rate_basis_label: '1kg',
    eta_minutes: 12,
    is_best_in_product: false,
    is_best_in_family: false,
    listed_paise: 24200,
    mrp_paise: 28500,
    price_source: 'extension',
    observed_at: '2026-10-19T08:10:00Z',
    freshness: 'fresh',
    in_stock: true,
  },
  {
    id: 'stp-2',
    product_key: 'pillsbury_chakki_fresh_atta_5kg',
    family_key: 'atta',
    category: 'staples',
    title: 'Pillsbury Chakki Fresh Atta',
    brand: 'Pillsbury',
    platform: 'zepto',
    pack_label: '5kg',
    icon: '🌾',
    url: 'https://www.zeptonow.com/pn/pillsbury-atta/pvid/202',
    unit_price_paise: 21900,
    unit_rate_paise: 4380,
    rate_basis_label: '1kg',
    eta_minutes: 10,
    is_best_in_product: true,
    is_best_in_family: true,
    listed_paise: 21900,
    mrp_paise: 27000,
    price_source: 'extension',
    observed_at: '2026-10-19T08:12:00Z',
    freshness: 'fresh',
    in_stock: true,
  },
]

describe('buildMatrixRows', () => {
  it('maps exact product needs and family needs across all 5 platforms and picks lowest in-stock deal', () => {
    const needs: SavedNeed[] = [
      {
        id: 1,
        list_id: 10,
        line_id: 'Fortune 5L',
        product_key: 'fortune_sunlite_oil_5l',
        family_key: null,
        quantity: null,
        qty: 1,
        need_by_minutes: null,
        lock_platform: null,
        status: 'open',
      },
      {
        id: 2,
        list_id: 10,
        line_id: 'Any Atta 5kg',
        product_key: null,
        family_key: 'atta',
        quantity: '5kg',
        qty: 1,
        need_by_minutes: null,
        lock_platform: null,
        status: 'open',
      },
    ]

    const rows = buildMatrixRows(needs, SAMPLE_DEALS)
    expect(rows).toHaveLength(2)

    expect(rows[0].need.line_id).toBe('Fortune 5L')
    expect(rows[0].byPlatform.amazon?.id).toBe('stp-4')
    expect(rows[0].byPlatform.flipkart?.id).toBe('stp-5')
    expect(rows[0].byPlatform.blinkit).toBeNull()
    expect(rows[0].bestPlatform).toBe('amazon')

    expect(rows[1].need.line_id).toBe('Any Atta 5kg')
    expect(rows[1].byPlatform.blinkit?.id).toBe('stp-1')
    expect(rows[1].byPlatform.zepto?.id).toBe('stp-2')
    expect(rows[1].bestPlatform).toBe('zepto')
  })
})
