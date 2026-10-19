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
  url: string
  unit_price_paise: number
  unit_rate_paise: number
  rate_basis_label: string
  eta_minutes: number
  is_best_in_product: boolean
  is_best_in_family: boolean
  listed_paise: number
  mrp_paise: number
  price_source: 'sample' | 'manual' | 'link' | 'extension' | 'fetcher'
  observed_at: string | null
  freshness: 'sample' | 'fresh' | 'ok' | 'stale'
  in_stock: boolean
}

export interface PriceIn {
  listing_id: string
  listed_paise: number
  mrp_paise: number
  member_price_paise: number | null
  in_stock: boolean
  eta_minutes: number | null
  note: string | null
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
    url?: string
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

export class UnauthorizedError extends Error {}

// Called on any 401 so the app can drop back to the sign-in screen.
let onUnauthorized: () => void = () => {}
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? 'GET').toUpperCase()
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  // CSRF: the API rejects state-changing requests without this header (cross-site forms can't send it).
  if (method !== 'GET') headers['X-DealScour'] = '1'
  const res = await fetch(path, { credentials: 'same-origin', ...init, headers })
  if (res.status === 401) {
    onUnauthorized()
    throw new UnauthorizedError('Please sign in')
  }
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

// ---- Saved data: lists, offers, baskets (backend/app/api/v1/{lists,offers,baskets}.py) ----

export interface ListSummary {
  id: number
  name: string
  kind: 'quick' | 'monthly' | 'event'
  archived: boolean
  created_at: string
  open_needs: number
}

export interface SavedNeed {
  id: number
  list_id: number
  line_id: string
  product_key: string | null
  family_key: string | null
  quantity: string | null
  qty: number
  need_by_minutes: number | null
  lock_platform: Platform | null
  status: 'open' | 'planned' | 'bought' | 'dropped'
}

export interface ListDetail extends Omit<ListSummary, 'open_needs'> {
  needs: SavedNeed[]
}

export interface SavedOffer extends Omit<OfferIn, 'id'> {
  id: number
  code: string
  valid_to: string | null
  note: string | null
  archived: boolean
}

export interface BasketLine {
  id: number
  listing_id: string
  line_id: string
  title: string
  pack_label: string
  packs: number
  unit_price_paise: number
  line_total_paise: number
  is_filler: boolean
}

export type BasketStatus = 'ready' | 'pending' | 'placed' | 'settled' | 'released'

export interface Basket {
  id: number
  plan_run_id: number
  platform: Platform
  status: BasketStatus
  target_offer_code: string | null
  threshold_paise: number | null
  shortfall_paise: number | null
  planned_net_paise: number
  offer_value_expected_paise: number
  actual_paid_paise: number | null
  offer_value_received_paise: number | null
  placed_at: string | null
  created_at: string
  lines: BasketLine[]
}

export interface Ledger {
  placed_count: number
  paid_paise: number
  offer_expected_paise: number
  offer_received_paise: number
  cashback_pending_paise: number
}

export interface ScourTarget {
  listing_id: string
  platform: Platform
  url: string
  title: string
  brand: string
  pack_label: string
  product_key: string
  family_key: string
  freshness: Deal['freshness']
  price_source: Deal['price_source']
}

export interface PriceCaptureIn {
  listing_id?: string | null
  url?: string | null
  listed_paise: number
  mrp_paise?: number | null
  member_price_paise?: number | null
  in_stock?: boolean
  eta_minutes?: number | null
  note?: string | null
}

const json = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) })

export const api = {
  lists: () => call<ListSummary[]>('/api/v1/lists'),
  createList: (name: string, kind: ListSummary['kind']) => call<ListSummary>('/api/v1/lists', json({ name, kind })),
  list: (id: number) => call<ListDetail>(`/api/v1/lists/${id}`),
  scourTargets: (listId: number) => call<{ list_id: number; targets: ScourTarget[] }>(`/api/v1/lists/${listId}/scour-targets`),
  applyQuickBundle: (listId: number, bundle: 'dryfruits_500g' = 'dryfruits_500g') =>
    call<{ list_id: number; bundle: string; added_needs: number }>(`/api/v1/lists/${listId}/quick-bundle`, json({ bundle })),
  addNeed: (listId: number, need: Omit<NeedIn, 'line_id'> & { line_id: string }) =>
    call<SavedNeed>(`/api/v1/lists/${listId}/needs`, json(need)),
  updateNeed: (id: number, patch: Partial<SavedNeed>) =>
    call<SavedNeed>(`/api/v1/needs/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  dropNeed: (id: number) => call<SavedNeed>(`/api/v1/needs/${id}`, { method: 'DELETE' }),
  planList: (listId: number, members: Platform[], fillers: FillerIn[]) =>
    call<PlanSetOut & { plan_run_id: number }>(`/api/v1/lists/${listId}/plan`, json({ members, fillers })),
  accept: (runId: number, label: string) => call<Basket[]>(`/api/v1/plan-runs/${runId}/accept`, json({ label })),

  offers: (includeArchived = false) => call<SavedOffer[]>(`/api/v1/offers?include_archived=${includeArchived}`),
  createOffer: (offer: Omit<OfferIn, 'id'> & { code: string; valid_to?: string | null; note?: string | null }) =>
    call<SavedOffer>('/api/v1/offers', json(offer)),
  archiveOffer: (id: number) => call<SavedOffer>(`/api/v1/offers/${id}/archive`, { method: 'POST' }),

  baskets: () => call<Basket[]>('/api/v1/baskets'),
  place: (id: number, actualPaid: number, withoutOffer = false) =>
    call<Basket>(`/api/v1/baskets/${id}/place`, json({ actual_paid_paise: actualPaid, without_offer: withoutOffer })),
  cashback: (id: number, received: number) => call<Basket>(`/api/v1/baskets/${id}/cashback`, json({ received_paise: received })),
  release: (id: number) => call<Basket>(`/api/v1/baskets/${id}/release`, { method: 'POST' }),
  addLine: (id: number, listingId: string, lineId: string) =>
    call<Basket>(`/api/v1/baskets/${id}/lines`, json({ listing_id: listingId, line_id: lineId })),
  ledger: () => call<Ledger>('/api/v1/ledger/summary'),

  observePrice: (p: PriceIn) => call<unknown>('/api/v1/prices', json(p)),
  capturePrice: (p: PriceCaptureIn) => call<unknown>('/api/v1/prices/capture', json(p)),
}

// ---- Auth and household (backend/app/api/v1/{auth,households}.py) ----

export interface Me {
  user: { id: number; email: string; name: string | null }
  household_id: number
  role: 'owner' | 'member'
}

export interface Member {
  user_id: number
  email: string
  name: string | null
  role: 'owner' | 'member'
}

export const auth = {
  me: () => call<Me>('/api/v1/auth/me'),
  requestCode: (email: string, inviteCode: string | null) =>
    call<{ sent: boolean }>('/api/v1/auth/request-code', json({ email, invite_code: inviteCode })),
  verify: (email: string, code: string, inviteCode: string | null, name: string | null) =>
    call<Me>('/api/v1/auth/verify', json({ email, code, invite_code: inviteCode, name })),
  logout: () => call<unknown>('/api/v1/auth/logout', { method: 'POST' }),
  members: () => call<Member[]>('/api/v1/households/members'),
  invite: () => call<{ invite_code: string; expires_at: string }>('/api/v1/households/invites', { method: 'POST' }),
  removeMember: (userId: number) => call<unknown>(`/api/v1/households/members/${userId}`, { method: 'DELETE' }),
}

// ---- Custom listings + fetcher (backend/app/api/v1/{listings,sources}.py) ----

export interface ProductRef {
  platform: Platform
  sku: string
  url: string
}

export interface NewListing {
  url: string
  title: string
  brand: string
  pack_label: string
  category: string
  family_key: string
  listed_paise: number
  mrp_paise: number
  member_price_paise: number | null
  in_stock: boolean
}

export interface Family {
  family_key: string
  count: number
  units: string[]
}

export interface SourceStatus {
  platform: Platform
  enabled_by_config: boolean
  consecutive_failures: number
  disabled_until: string | null
  last_success_at: string | null
  last_error: string | null
}

export const catalog = {
  parseLink: (url: string) => call<ProductRef>('/api/v1/listings/parse', json({ url })),
  addListing: (l: NewListing) => call<{ listing_id: string; product_key: string }>('/api/v1/listings', json(l)),
  families: () => call<Family[]>('/api/v1/catalog/families'),
  refreshPrices: () => call<{ queued: number }>('/api/v1/sources/refresh', { method: 'POST' }),
  sourceStatus: () => call<{ platforms: SourceStatus[]; quick_commerce: string }>('/api/v1/sources/status'),
}
