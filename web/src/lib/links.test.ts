import { describe, expect, it } from 'vitest'
import { isProductPage } from './links'

describe('isProductPage', () => {
  it('accepts product pages on each shop', () => {
    expect(isProductPage('https://www.amazon.in/dp/B018E0G4MU')).toBe(true)
    expect(isProductPage('https://www.flipkart.com/on-whey/p/itm99a7adea73fa0?pid=PSLHKQ8T2FYJ4H33')).toBe(true)
    expect(isProductPage('https://blinkit.com/prn/amul-butter/prid/12345')).toBe(true)
    expect(isProductPage('https://www.zeptonow.com/pn/amul-butter/pvid/1b2c3d4e-0000-4000-8000-000000000000')).toBe(true)
    expect(isProductPage('https://www.swiggy.com/instamart/item/ABC123')).toBe(true)
  })

  it('rejects search, home and malformed links', () => {
    expect(isProductPage('https://www.amazon.in/s?k=amul+butter')).toBe(false)
    expect(isProductPage('https://www.flipkart.com/search?q=butter')).toBe(false)
    expect(isProductPage('https://www.flipkart.com/on-whey/p/itm99a7adea73fa0')).toBe(false)
    expect(isProductPage('https://www.zeptonow.com/')).toBe(false)
    expect(isProductPage('http://www.amazon.in/dp/B018E0G4MU')).toBe(false)
    expect(isProductPage('not a url')).toBe(false)
  })
})
