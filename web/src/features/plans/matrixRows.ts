import { PLATFORMS, type Deal, type Platform, type SavedNeed } from '../../lib/api'

export interface MatrixRow {
  need: SavedNeed
  icon: string
  byPlatform: Record<Platform, Deal | null>
  bestPlatform: Platform | null
}

export function buildMatrixRows(needs: SavedNeed[], deals: Deal[]): MatrixRow[] {
  return needs.map((need) => {
    const byPlatform: Record<Platform, Deal | null> = {
      amazon: null,
      flipkart: null,
      blinkit: null,
      instamart: null,
      zepto: null,
    }

    let icon = '🛒'
    for (const d of deals) {
      const matchesProduct = need.product_key !== null && d.product_key === need.product_key
      const matchesFamily = need.product_key === null && need.family_key !== null && d.family_key === need.family_key
      if (!matchesProduct && !matchesFamily) continue

      icon = d.icon || icon
      const prev = byPlatform[d.platform]
      if (!prev || d.unit_rate_paise < prev.unit_rate_paise) {
        byPlatform[d.platform] = d
      }
    }

    let bestPlatform: Platform | null = null
    let bestRate = Infinity
    for (const p of PLATFORMS) {
      const candidate = byPlatform[p]
      if (candidate && candidate.in_stock && candidate.unit_rate_paise < bestRate) {
        bestRate = candidate.unit_rate_paise
        bestPlatform = p
      }
    }

    return {
      need,
      icon,
      byPlatform,
      bestPlatform,
    }
  })
}
