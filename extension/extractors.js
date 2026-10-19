// Injected into the rendered product tab via chrome.scripting.executeScript.
// Strictly read-only price/MRP/stock/ETA extraction in integer paise (ADR-009, ADR-020).
function extractDealScourPriceFromDOM() {
  function parseRupeesToPaise(raw) {
    if (!raw) return null;
    const cleaned = String(raw).replace(/[^0-9.]/g, '');
    if (!cleaned) return null;
    const val = Number(cleaned);
    if (!Number.isFinite(val) || val <= 0) return null;
    return Math.round(val * 100);
  }

  function extractFromJsonLd() {
    const scripts = document.querySelectorAll('script[type="application/ld+json"]');
    for (const s of scripts) {
      try {
        const parsed = JSON.parse(s.textContent || '');
        const items = Array.isArray(parsed) ? parsed : [parsed];
        for (const item of items) {
          if (item && item['@type'] === 'Product' && item.offers) {
            const offer = Array.isArray(item.offers) ? item.offers[0] : item.offers;
            const listed = parseRupeesToPaise(offer && offer.price);
            if (listed) {
              const avail = String((offer && offer.availability) || '').toLowerCase();
              const inStock = !avail.includes('outofstock') && !avail.includes('soldout');
              return { listed_paise: listed, in_stock: inStock };
            }
          }
        }
      } catch {
        // ignore malformed json-ld
      }
    }
    return null;
  }

  const host = window.location.hostname.toLowerCase();
  const bodyText = (document.body && document.body.innerText) || '';
  const outOfStockText = /currently unavailable|out of stock|sold out/i.test(bodyText);

  let listed_paise = null;
  let mrp_paise = null;
  let in_stock = !outOfStockText;
  let eta_minutes = null;

  const ld = extractFromJsonLd();
  if (ld) {
    listed_paise = ld.listed_paise;
    in_stock = ld.in_stock;
  }

  if (host.includes('amazon.in')) {
    const wholeEl = document.querySelector('#corePriceDisplay_desktop_feature_div .a-price-whole, .a-price .a-price-whole');
    const fracEl = document.querySelector('#corePriceDisplay_desktop_feature_div .a-price-fraction, .a-price .a-price-fraction');
    if (wholeEl && !listed_paise) {
      const combined = `${wholeEl.textContent || ''}.${(fracEl && fracEl.textContent) || '00'}`;
      listed_paise = parseRupeesToPaise(combined);
    }
    const mrpEl = document.querySelector('.basisPrice .a-offscreen, [data-a-strike="true"] .a-offscreen');
    if (mrpEl) {
      mrp_paise = parseRupeesToPaise(mrpEl.textContent);
    }
  } else {
    // Quick-commerce & Flipkart fallback: scan visible ₹ price tokens near top of product card
    const rupeeMatches = [...bodyText.matchAll(/₹\s?([\d,]+(?:\.\d{1,2})?)/g)]
      .map((m) => parseRupeesToPaise(m[1]))
      .filter((v) => v !== null && v >= 500 && v <= 5000000);
    if (!listed_paise && rupeeMatches.length > 0) {
      listed_paise = rupeeMatches[0];
    }
    if (!mrp_paise && rupeeMatches.length > 1 && rupeeMatches[1] >= listed_paise) {
      mrp_paise = rupeeMatches[1];
    }
    const etaMatch = bodyText.match(/(\d{1,2})\s*(?:mins?|minutes)/i);
    if (etaMatch) {
      eta_minutes = Number(etaMatch[1]);
    }
  }

  if (!listed_paise) {
    return null;
  }
  if (!mrp_paise || mrp_paise < listed_paise) {
    mrp_paise = listed_paise;
  }

  return {
    listed_paise,
    mrp_paise,
    in_stock,
    eta_minutes,
  };
}

if (typeof module !== 'undefined') {
  module.exports = { extractDealScourPriceFromDOM };
}
