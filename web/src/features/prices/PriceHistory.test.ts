import { describe, expect, it } from 'vitest'
import { buildSparklinePoints } from './PriceHistory'

describe('PriceHistory sparkline generator', () => {
  it('returns empty string when fewer than 2 data points are provided', () => {
    expect(buildSparklinePoints([])).toBe('')
    expect(buildSparklinePoints([25000])).toBe('')
  })

  it('computes coordinate string for points properly scaled', () => {
    // 3 observations: 200 (low), 250 (mid), 300 (high)
    const points = buildSparklinePoints([200, 250, 300], 100, 50, 0)
    // At padding 0:
    // point 0: x = 0, y = 50 (bottom)
    // point 1: x = 50, y = 25 (mid)
    // point 2: x = 100, y = 0 (top)
    expect(points).toBe('0.0,50.0 50.0,25.0 100.0,0.0')
  })

  it('handles flat prices without dividing by zero', () => {
    const points = buildSparklinePoints([25000, 25000], 100, 50, 0)
    expect(points).toBe('0.0,50.0 100.0,50.0')
  })
})
