import { describe, expect, it } from 'vitest'
import { formatINR } from './money'

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
