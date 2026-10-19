// True when a shop URL points at one product, not a search or home page.
const PRODUCT_PATHS = [
  /\/dp\/[A-Z0-9]{10}/,
  /\/gp\/product\/[A-Z0-9]{10}/,
  /\/p\/itm[a-z0-9]+/i,
  /\/prid\/\d+/,
  /\/pvid\/[0-9a-f-]+/i,
  /\/instamart\/item\/\w+/,
  /^\/p\/[a-z0-9-]+-[A-Z0-9]{8,}\/?$/,
]

export function isProductPage(url: string): boolean {
  try {
    const u = new URL(url)
    if (u.protocol !== 'https:') return false
    if (/\/p\/itm/i.test(u.pathname) && !u.searchParams.get('pid')) return false
    return PRODUCT_PATHS.some((re) => re.test(u.pathname))
  } catch {
    return false
  }
}

