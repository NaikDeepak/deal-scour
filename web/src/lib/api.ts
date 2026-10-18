// Types mirror backend/app/api/v1/{deals,plans}.py. All money is integer paise (ADR-009).

export type Platform = 'amazon' | 'flipkart' | 'blinkit' | 'instamart' | 'zepto'
export const PLATFORMS: Platform[] = ['amazon', 'flipkart', 'blinkit', 'instamart', 'zepto']

export const PLATFORM_META: Record<Platform, { name: string; membership: string; color: string }> = {
  amazon: { name: 'Amazon', membership: 'Prime', color: '#FF9900' },
  flipkart: { name: 'Flipkart', membership: 'Flipkart Plus', color: '#2874F0' },
  blinkit: { name: 'Blinkit', membership: 'Zomato Gold', color: '#F8CB46' },
  instamart: { name: 'Instamart', membership: 'Swiggy One', color: '#FC8019' },
  zepto: { name: 'Zepto', membership: 'Zepto Pass', color: '#9333EA' },
}

export interface Deal {
  id: string
  product_key: string
  family_key: string
  category: string
  title: string
  brand: string
  platform: Platform
  pack_label: string
  icon: string
  unit_price_paise: number
  unit_rate_paise: number
  rate_basis_label: string
  eta_minutes: number
  is_best_in_product: boolean
  is_best_in_family: boolean
}

export interface OfferIn {
  id: string
  platform: Platform
  kind: 'flat' | 'pct_cap' | 'tiered'
  min_order_paise: number
  value_paise: number
  rate_bp: number
  cap_paise: number | null
  tiers: [number, number][]
  uses_left: number
  stack_group: string
  value_type: 'cash' | 'instant' | 'amazon_pay' | 'supercoins'
  multiplier_bp: number | null
  eligible_categories: string[] | null
}

// Exactly one of product_key (this exact pack) or family_key + quantity (any brand/pack, e.g. "5L").
export interface NeedIn {
  line_id: string
  product_key: string | null
  family_key: string | null
  quantity: string | null
  qty: number
  need_by_minutes: number | null
  lock_platform: Platform | null
}

export interface FillerIn {
  filler_id: string
  listing_id: string
  score: number
}

export interface PlanRequest {
  members: Platform[]
  needs: NeedIn[]
  offers: OfferIn[]
  fillers: FillerIn[]
}

export interface Reason {
  code: string
  platform: Platform
  amount_paise: number
  line_ids: string[]
  text: string
}

export interface OrderOut {
  platform: Platform
  status: 'now' | 'pending'
  lines: {
    line_id: string
    listing_id: string
    title: string
    pack_label: string
    packs: number
    unit_price_paise: number
    line_total_paise: number
    is_filler: boolean
  }[]
  subtotal_paise: number
  fees: { delivery: number; handling: number; platform: number; small_cart: number; surge: number; total: number }
  offers_applied: { offer_id: string; face_value_paise: number; effective_value_paise: number }[]
  net_paise: number
  shortfall_paise: number | null
  target_offer_id: string | null
}

export interface PlanOut {
  orders: OrderOut[]
  total_subtotal_paise: number
  total_fees_paise: number
  total_offer_value_paise: number
  total_net_paise: number
  unpriced: string[]
}

export interface LabelledPlanOut extends PlanOut {
  label: 'cheapest_now' | 'max_savings' | 'fastest'
  effective_cost_paise: number
  savings_vs_baseline_paise: number
  reasons: Reason[]
}

export interface PlanSetOut {
  baseline: PlanOut
  plans: LabelledPlanOut[]
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...init })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    const detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body)
    throw new Error(`${res.status}: ${detail}`)
  }
  return res.json() as Promise<T>
}

export function fetchDeals(members: Platform[]): Promise<{ count: number; deals: Deal[] }> {
  return call(`/api/v1/deals?members=${members.join(',')}`)
}

export function requestPlans(req: PlanRequest): Promise<PlanSetOut> {
  return call('/api/v1/plans', { method: 'POST', body: JSON.stringify(req) })
}
