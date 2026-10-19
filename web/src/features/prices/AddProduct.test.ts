import { describe, expect, it } from 'vitest'
import { parseBulkUrls, sourceLabel } from './AddProduct'

describe('AddProduct helpers and autofill mapping', () => {
  it('parses bulk URLs up to max 20, filtering empty lines', () => {
    const raw = `
      https://www.amazon.in/dp/B001
      https://www.amazon.in/dp/B002

      https://blinkit.com/prn/item/prid/123
    `
    const urls = parseBulkUrls(raw)
    expect(urls).toEqual([
      'https://www.amazon.in/dp/B001',
      'https://www.amazon.in/dp/B002',
      'https://blinkit.com/prn/item/prid/123',
    ])

    const many = Array.from({ length: 25 }, (_, i) => `https://link.com/${i}`).join('\n')
    expect(parseBulkUrls(many)).toHaveLength(20)
  })

  it('maps source identifiers to user-facing labels', () => {
    expect(sourceLabel('page')).toEqual({
      label: 'from page',
      className: 'bg-emerald-100 text-emerald-800',
    })
    expect(sourceLabel('rules')).toEqual({
      label: 'guessed',
      className: 'bg-sky-100 text-sky-800',
    })
    expect(sourceLabel('gemini')).toEqual({
      label: 'AI',
      className: 'bg-purple-100 text-purple-800',
    })
    expect(sourceLabel('slug')).toEqual({
      label: 'from link',
      className: 'bg-slate-100 text-slate-700',
    })
    expect(sourceLabel('unknown')).toBeNull()
    expect(sourceLabel(undefined)).toBeNull()
  })

  it('correctly interprets mocked autofill response structure', () => {
    const mockAutofill = {
      url: 'https://www.amazon.in/dp/B072HG4WNC',
      platform: 'amazon' as const,
      sku: 'B072HG4WNC',
      title: 'Amul Butter 500 g',
      brand: 'Amul',
      pack_label: '500g',
      category: 'dairy',
      family_key: 'butter',
      listed_paise: 27500,
      mrp_paise: 29000,
      in_stock: true,
      sources: {
        title: 'page',
        listed_paise: 'page',
        brand: 'rules',
        pack_label: 'rules',
        family_key: 'gemini',
      },
    }

    expect(mockAutofill.title).toBe('Amul Butter 500 g')
    expect(mockAutofill.listed_paise / 100).toBe(275)
    expect(sourceLabel(mockAutofill.sources.title)?.label).toBe('from page')
    expect(sourceLabel(mockAutofill.sources.brand)?.label).toBe('guessed')
    expect(sourceLabel(mockAutofill.sources.family_key)?.label).toBe('AI')
  })
})
