import { describe, expect, it } from 'vitest'
import { renderReasonLabel } from './DealsPage'

describe('DealsPage reason rendering and formatting', () => {
  it('renders below_target reason chip label and style', () => {
    const badge = renderReasonLabel('below_target')
    expect(badge.label).toBe('🎯 Below target')
    expect(badge.className).toContain('text-emerald-800')
  })

  it('renders low_30d reason chip label and style', () => {
    const badge = renderReasonLabel('low_30d')
    expect(badge.label).toBe('📉 30-day low')
    expect(badge.className).toContain('text-sky-800')
  })

  it('renders under_avg reason chip with percentage', () => {
    const badge = renderReasonLabel('under_avg', 18.5)
    expect(badge.label).toBe('⚡ 18.5% under avg')
    expect(badge.className).toContain('text-amber-800')

    const fallbackBadge = renderReasonLabel('under_avg')
    expect(fallbackBadge.label).toBe('⚡ ≥15% under avg')
  })

  it('formats unknown reasons gracefully', () => {
    const badge = renderReasonLabel('custom_reason')
    expect(badge.label).toBe('custom_reason')
  })
})
