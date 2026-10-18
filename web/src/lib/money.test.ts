import { describe, expect, it } from 'vitest'
import { formatINR, parseRupees } from './money'

// Same cases as backend tests/core/test_money.py (format_inr), so both sides render identically.
describe('formatINR', () => {
  it.each([
    [125000, '₹1,250'],
    [12500000, '₹1,25,000'],
    [1234567800, '₹1,23,45,678'],
    [28950, '₹289.50'],
    [5, '₹0.05'],
    [0, '₹0'],
    [-5000, '-₹50'],
  ])('%i → %s', (paise, expected) => {
    expect(formatINR(paise)).toBe(expected)
  })

  it('rejects non-integer paise', () => {
    expect(() => formatINR(289.5)).toThrow(TypeError)
  })
})

describe('parseRupees', () => {
  it.each([
    ['500', 50000],
    ['1,250', 125000],
    ['49.5', 4950],
    ['49.05', 4905],
    [' 0 ', 0],
  ])('%s → %i', (input, expected) => {
    expect(parseRupees(input)).toBe(expected)
  })

  it.each(['', 'abc', '-5', '1.234', '1e3'])('rejects %s', (input) => {
    expect(parseRupees(input)).toBeNull()
  })
})
