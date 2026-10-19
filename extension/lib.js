// DealScour Extension Pure Helpers
// Money is integer paise everywhere (ADR-009). No external dependencies.

const ALLOWED_HOSTS = new Set([
  'amazon.in',
  'www.amazon.in',
  'flipkart.com',
  'www.flipkart.com',
  'blinkit.com',
  'www.swiggy.com',
  'swiggy.com',
  'instamart.in',
  'www.instamart.in',
  'www.zeptonow.com',
  'zeptonow.com',
  'zepto.com',
  'www.zepto.com',
]);

function parseRupeesToPaise(raw) {
  if (raw == null) return null;
  const str = String(raw).trim();
  if (!str || str.includes('-')) return null;
  const cleaned = str.replace(/,/g, '').replace(/^[^\d.]*/, '').replace(/[^\d.]*$/, '');
  if (!cleaned || !/^\d+(?:\.\d+)?$/.test(cleaned)) return null;
  const val = Number(cleaned);
  if (!Number.isFinite(val) || val <= 0) return null;
  return Math.round(val * 100);
}

function priceFromJsonLd(texts) {
  if (!Array.isArray(texts)) return null;
  for (const raw of texts) {
    if (!raw) continue;
    const text = typeof raw === 'string' ? raw : (raw.textContent || '');
    try {
      const parsed = JSON.parse(text);
      let items = [];
      if (Array.isArray(parsed)) {
        items = parsed;
      } else if (parsed && Array.isArray(parsed['@graph'])) {
        items = parsed['@graph'];
      } else if (parsed && typeof parsed === 'object') {
        items = [parsed];
      }
      for (const item of items) {
        if (!item) continue;
        const type = item['@type'];
        const isProduct = type === 'Product' || (Array.isArray(type) && type.includes('Product'));
        if (isProduct && item.offers) {
          const offers = Array.isArray(item.offers) ? item.offers : [item.offers];
          for (const offer of offers) {
            if (!offer) continue;
            const priceVal = offer.price ?? offer.lowPrice;
            const listed = parseRupeesToPaise(priceVal);
            if (listed) {
              const avail = String(offer.availability || '').toLowerCase();
              const inStock = !avail.includes('outofstock') && !avail.includes('soldout');
              return {
                listed_paise: listed,
                in_stock: inStock,
                valueOf() {
                  return this.listed_paise;
                },
              };
            }
          }
        }
      }
    } catch {
      // ignore malformed json-ld
    }
  }
  return null;
}

function isAllowedUrl(rawUrl) {
  if (!rawUrl || typeof rawUrl !== 'string') return false;
  try {
    const parsed = new URL(rawUrl);
    if (parsed.protocol !== 'https:') return false;
    const host = parsed.hostname.toLowerCase();
    return ALLOWED_HOSTS.has(host);
  } catch {
    return false;
  }
}

function isProductPageUrl(rawUrl) {
  if (!rawUrl || typeof rawUrl !== 'string') return false;
  try {
    const parsed = new URL(rawUrl);
    if (parsed.protocol !== 'https:') return false;
    const host = parsed.hostname.toLowerCase().replace(/^www\./, '');
    const path = parsed.pathname;
    if (path.includes('/sspa/click') || path.includes('/gp/slredirect')) return false;
    if (path.includes('/dp/') || path.includes('/gp/product/')) return true;
    if (host === 'instamart.in') {
      return /^\/p\/[a-z0-9-]+-[A-Z0-9]{8,}\/?$/.test(path);
    }
    if (path.includes('/p/') && (parsed.searchParams.has('pid') || /\/p\/itm/i.test(path))) return true;
    if (path.includes('/prid/')) return true;
    if (path.includes('/pvid/')) return true;
    if (path.includes('/instamart/item/')) return true;
    return false;
  } catch {
    return false;
  }
}

function pickAddButton(candidates, packLabel) {
  if (!candidates) return null;
  const list = Array.from(candidates);

  function isVisible(c) {
    if (!c) return false;
    if (typeof c.visible === 'boolean') return c.visible;
    if (c.offsetParent !== undefined) return c.offsetParent !== null;
    return true;
  }

  function getAttr(c, attr) {
    if (!c) return '';
    if (typeof c[attr] === 'string') return c[attr];
    if (typeof c.getAttribute === 'function') {
      const val = c.getAttribute(attr);
      if (typeof val === 'string') return val;
    }
    return '';
  }

  function getText(c) {
    if (!c) return '';
    return (c.textContent || c.innerText || c.value || '').trim();
  }

  const FORBIDDEN_RE = /buy now|place order|checkout|proceed|pay/i;
  const GENERIC_ADD_RE = /^(add|add to cart|add to bag|\+\s*add)$/i;

  const visibleCandidates = list.filter(isVisible);

  // 1. Prefer platform-specific IDs (#add-to-cart-button, button[name="submit.add-to-cart"])
  for (const c of visibleCandidates) {
    const id = getAttr(c, 'id');
    const name = getAttr(c, 'name');
    const text = getText(c);
    const aria = getAttr(c, 'aria-label');
    if (FORBIDDEN_RE.test(text) || FORBIDDEN_RE.test(aria)) {
      continue;
    }
    if (id === 'add-to-cart-button' || name === 'submit.add-to-cart') {
      return c;
    }
  }

  // 2. Otherwise accept generic Add/Add to cart only if it is the ONLY visible match
  const genericMatches = visibleCandidates.filter((c) => {
    const text = getText(c);
    const aria = getAttr(c, 'aria-label');
    if (FORBIDDEN_RE.test(text) || FORBIDDEN_RE.test(aria)) {
      return false;
    }
    return GENERIC_ADD_RE.test(text);
  });

  if (genericMatches.length === 1) {
    return genericMatches[0];
  }

  return null;
}

function normalizeHost(h) {
  return String(h || '').replace(/^www\./, '').toLowerCase();
}

function extractProductId(rawUrl) {
  if (!rawUrl || typeof rawUrl !== 'string') return null;
  try {
    const parsed = new URL(rawUrl);
    const path = parsed.pathname;
    const host = normalizeHost(parsed.hostname);

    // Amazon ASIN: 10 chars after /dp/ or /gp/product/ or /product/
    if (host.includes('amazon.')) {
      const m = path.match(/\/(?:dp|gp\/product|product)\/([A-Za-z0-9]{10})/i);
      return m ? m[1].toUpperCase() : null;
    }

    // Flipkart pid: query param ?pid= or /p/itm...
    if (host.includes('flipkart.')) {
      if (parsed.searchParams.has('pid')) {
        return parsed.searchParams.get('pid');
      }
      const m = path.match(/\/p\/(itm[A-Za-z0-9]+)/i);
      return m ? m[1] : null;
    }

    // Blinkit prid: /prid/...
    if (host.includes('blinkit.')) {
      const m = path.match(/\/prid\/([A-Za-z0-9_-]+)/i);
      return m ? m[1] : null;
    }

    // Zepto pvid: /pvid/...
    if (host.includes('zepto')) {
      const m = path.match(/\/pvid\/([A-Za-z0-9_-]+)/i);
      return m ? m[1] : null;
    }

    // Swiggy Instamart item id: /instamart/item/...
    if (host.includes('swiggy.')) {
      const m = path.match(/\/instamart\/item\/([A-Za-z0-9_-]+)/i);
      return m ? m[1] : null;
    }

    // Instamart new domain: instamart.in/p/<slug>-<ID>
    if (host === 'instamart.in') {
      const m = path.match(/^\/p\/[a-z0-9-]+-([A-Z0-9]{8,})\/?$/);
      return m ? m[1] : null;
    }

    return null;
  } catch {
    return null;
  }
}

function isMatchingProductPage(targetUrl, landedUrl) {
  if (!targetUrl || !landedUrl) return false;
  try {
    const targetParsed = new URL(targetUrl);
    const landedParsed = new URL(landedUrl);
    if (normalizeHost(targetParsed.hostname) !== normalizeHost(landedParsed.hostname)) {
      return false;
    }
    const targetId = extractProductId(targetUrl);
    const landedId = extractProductId(landedUrl);
    if (!targetId || !landedId) {
      return false;
    }
    return targetId === landedId;
  } catch {
    return false;
  }
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    ALLOWED_HOSTS,
    parseRupeesToPaise,
    priceFromJsonLd,
    isAllowedUrl,
    isProductPageUrl,
    pickAddButton,
    extractProductId,
    isMatchingProductPage,
  };
}
