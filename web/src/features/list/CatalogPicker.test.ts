import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { CatalogProductItem, SavedNeed } from '../../lib/api'
import PlansPage from '../plans/PlansPage'
import { CatalogResultsSection, catalogProductToNeed, searchCatalogItems } from './CatalogPicker'

const SAMPLE_CATALOG: CatalogProductItem[] = [
  {
    id: 1,
    seed_product_id: 'DS-0001',
    name: 'Tata Sampann Toor/Arhar Dal',
    brand: 'Tata Sampann',
    category: 'Dal & Pulses',
    family_key: 'toor_dal',
    pack_label: '600g',
    target_pack_weight_g: 600,
    suggestions: [],
  },
  {
    id: 2,
    seed_product_id: 'DF-0001',
    name: 'Happilo California Almonds',
    brand: 'Happilo',
    category: 'Almonds',
    family_key: 'almonds',
    pack_label: '500g',
    target_pack_weight_g: 500,
    suggestions: [],
  },
]

describe('CatalogPicker', () => {
  it('renders catalog results under "From your catalog" heading with Find on shops button', () => {
    const html = renderToStaticMarkup(
      createElement(CatalogResultsSection, {
        items: SAMPLE_CATALOG,
        onPickCatalog: () => {},
        onFindOnShops: () => {},
      }),
    )

    expect(html).toContain('From your catalog')
    expect(html).toContain('Tata Sampann Toor/Arhar Dal')
    expect(html).toContain('600g')
    expect(html).toContain('Find on shops')
  })

  it('caps rendered catalog results at 8 items', () => {
    const tenItems: CatalogProductItem[] = Array.from({ length: 10 }, (_, idx) => ({
      id: idx + 1,
      seed_product_id: `DS-00${idx + 1}`,
      name: `Catalog Item ${idx + 1}`,
      brand: 'Brand',
      category: 'Staples',
      family_key: 'staples',
      pack_label: '500g',
      target_pack_weight_g: 500,
      suggestions: [],
    }))

    const html = renderToStaticMarkup(
      createElement(CatalogResultsSection, {
        items: tenItems,
        onPickCatalog: () => {},
        onFindOnShops: () => {},
      }),
    )

    expect(html).toContain('Catalog Item 8')
    expect(html).not.toContain('Catalog Item 9')
  })

  it('builds a flexible family need with the catalog pack when a catalog item is picked', () => {
    const needPayload = catalogProductToNeed(SAMPLE_CATALOG[0])
    expect(needPayload).toEqual({
      line_id: 'Tata Sampann Toor/Arhar Dal 600g',
      product_key: null,
      family_key: 'toor_dal',
      quantity: '600g',
      qty: 1,
      need_by_minutes: null,
      lock_platform: null,
    })
  })

  it('Case 19: on the Plan page, typing "toor" shows the catalog result and a catalog need shows Find on shops', async () => {
    const matched = await searchCatalogItems('toor', async (q) =>
      SAMPLE_CATALOG.filter((item) => item.name.toLowerCase().includes(q.toLowerCase())),
    )
    expect(matched).toHaveLength(1)
    expect(matched[0].name).toBe('Tata Sampann Toor/Arhar Dal')

    const catalogNeed: SavedNeed = {
      id: 101,
      list_id: 1,
      line_id: 'Tata Sampann Toor/Arhar Dal 600g',
      product_key: null,
      family_key: 'toor_dal',
      quantity: '600g',
      qty: 1,
      need_by_minutes: null,
      lock_platform: null,
      status: 'open',
    }

    const html = renderToStaticMarkup(
      createElement(PlansPage, {
        onAccepted: () => {},
        initialCatalogQuery: 'toor',
        initialCatalogItems: matched,
        initialOpenNeeds: [catalogNeed],
      }),
    )

    expect(html).toContain('From your catalog')
    expect(html).toContain('Tata Sampann Toor/Arhar Dal')
    expect(html).toContain('Tata Sampann Toor/Arhar Dal 600g')
    // Both the catalog result and the catalog open need render a "Find on shops" button
    const findButtons = html.match(/Find on shops/g) ?? []
    expect(findButtons.length).toBeGreaterThanOrEqual(2)
  })
})

