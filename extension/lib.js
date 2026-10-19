// DealScour Extension Pure Helpers
// Money is integer paise everywhere (ADR-009). No external dependencies.

const PORTAL_ORIGINS = [
  'http://localhost:8000',
  'http://127.0.0.1:8000',
  'http://localhost:5173',
  'http://127.0.0.1:5173',
];

const DEALSCOUR_API_ORIGIN = 'http://localhost:8000';

const SEARCH_URL_RULES = {
  amazon: { host: 'www.amazon.in', path: '/s', param: 'k' },
  flipkart: { host: 'www.flipkart.com', path: '/search', param: 'q' },
  blinkit: { host: 'blinkit.com', path: '/s/', param: 'q' },
  zepto: { host: 'www.zepto.com', path: '/search', param: 'query' },
  instamart: { host: 'www.swiggy.com', path: '/instamart/search', param: 'query' },
};

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

function isAllowedSearchUrl(rawUrl, platform) {
  if (!rawUrl || typeof rawUrl !== 'string' || !platform || typeof platform !== 'string') {
    return false;
  }
  const rule = SEARCH_URL_RULES[platform.toLowerCase()];
  if (!rule) return false;
  try {
    const parsed = new URL(rawUrl);
    if (parsed.protocol !== 'https:') return false;
    if (parsed.hostname.toLowerCase() !== rule.host) return false;
    if (parsed.pathname !== rule.path) return false;
    const q = parsed.searchParams.get(rule.param);
    return typeof q === 'string' && q.trim().length > 0;
  } catch {
    return false;
  }
}

function parsePackLabel(rawText) {
  if (!rawText || typeof rawText !== 'string') return null;
  const s = rawText.trim();
  if (!s) return null;

  const UNIT_RE = '(?:g|gm|gms|gram|grams|kg|kgs|ml|mls|l|ltr|ltrs|litre|litres)';

  function formatResult(val, unitRaw, multiplier = 1) {
    const u = unitRaw.toLowerCase();
    const total = val * multiplier;
    if (!Number.isFinite(total) || total <= 0) return null;

    if (u === 'kg' || u === 'kgs') {
      return `${total}kg`;
    }
    if (u === 'l' || u === 'ltr' || u === 'ltrs' || u === 'litre' || u === 'litres') {
      return `${total}l`;
    }
    if (u === 'ml' || u === 'mls') {
      return `${total}ml`;
    }
    return `${total}g`;
  }

  // 1. Prefix multiplier with "Pack of N x Q" or "N x Q": e.g. "Pack of 3 x 200g", "3 x 200g"
  const prefixMult = s.match(
    new RegExp(`(?:pack\\s+of\\s+)?(\\d+)\\s*[xX*]\\s*(\\d+(?:\\.\\d+)?)\\s*(${UNIT_RE})\\b`, 'i')
  );
  if (prefixMult) {
    const mult = parseInt(prefixMult[1], 10);
    const val = parseFloat(prefixMult[2]);
    const unit = prefixMult[3];
    return formatResult(val, unit, mult);
  }

  // 2. Suffix multiplier with "(Pack of N)" or "Pack of N" or "[Pack of N]": e.g. "200 Gram (Pack Of 2)"
  const suffixPackOf = s.match(
    new RegExp(
      `(\\d+(?:\\.\\d+)?)\\s*(${UNIT_RE})\\b[^(]*[\\(\\[]?\\s*pack\\s+of\\s+(\\d+)\\s*[\\)\\]]?`,
      'i'
    )
  );
  if (suffixPackOf) {
    const val = parseFloat(suffixPackOf[1]);
    const unit = suffixPackOf[2];
    const mult = parseInt(suffixPackOf[3], 10);
    return formatResult(val, unit, mult);
  }

  // 3. Suffix multiplier "Q x N": e.g. "200g x 3"
  const suffixMult = s.match(
    new RegExp(`(\\d+(?:\\.\\d+)?)\\s*(${UNIT_RE})\\b\\s*[xX*]\\s*(\\d+)\\b`, 'i')
  );
  if (suffixMult) {
    const val = parseFloat(suffixMult[1]);
    const unit = suffixMult[2];
    const mult = parseInt(suffixMult[3], 10);
    return formatResult(val, unit, mult);
  }

  // 4. "Pack of N" with no quantity -> ambiguous / null
  if (/^\s*(?:\(?\s*pack\s+of\s+\d+\s*\)?)\s*$/i.test(s)) {
    return null;
  }

  // 5. Standard single quantity match: e.g. "1 Kg", "500gm"
  const matches = [...s.matchAll(new RegExp(`\\b(\\d+(?:\\.\\d+)?)\\s*(${UNIT_RE})\\b`, 'gi'))];
  if (matches.length === 1) {
    const val = parseFloat(matches[0][1]);
    const unit = matches[0][2];
    return formatResult(val, unit, 1);
  }

  return null;
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    PORTAL_ORIGINS,
    DEALSCOUR_API_ORIGIN,
    ALLOWED_HOSTS,
    parseRupeesToPaise,
    priceFromJsonLd,
    isAllowedUrl,
    isAllowedSearchUrl,
    isProductPageUrl,
    pickAddButton,
    extractProductId,
    isMatchingProductPage,
    parsePackLabel,
  };
}

