// Injected into the rendered product tab via chrome.scripting.executeScript.
// Strictly read-only price/MRP/stock/ETA extraction in integer paise (ADR-009, ADR-020).
function extractDealScourPriceFromDOM() {
  const parsePaise = typeof parseRupeesToPaise === 'function' ? parseRupeesToPaise : () => null;
  const getJsonLd = typeof priceFromJsonLd === 'function' ? priceFromJsonLd : () => null;

  const scripts = Array.from(document.querySelectorAll('script[type="application/ld+json"]'));
  const ld = getJsonLd(scripts);

  const host = window.location.hostname.toLowerCase();
  const bodyText = (document.body && document.body.innerText) || '';
  const outOfStockText = /currently unavailable|out of stock|sold out/i.test(bodyText);

  let listed_paise = null;
  let mrp_paise = null;
  let in_stock = !outOfStockText;
  let eta_minutes = null;

  if (ld) {
    listed_paise = ld.listed_paise;
    in_stock = ld.in_stock;
  }

  if (host.includes('amazon.in')) {
    const wholeEl = document.querySelector('#corePriceDisplay_desktop_feature_div .a-price-whole, .a-price .a-price-whole');
    const fracEl = document.querySelector('#corePriceDisplay_desktop_feature_div .a-price-fraction, .a-price .a-price-fraction');
    if (wholeEl && !listed_paise) {
      const combined = `${wholeEl.textContent || ''}.${(fracEl && fracEl.textContent) || '00'}`;
      listed_paise = parsePaise(combined);
    }
    const mrpEl = document.querySelector('.basisPrice .a-offscreen, [data-a-strike="true"] .a-offscreen');
    if (mrpEl) {
      mrp_paise = parsePaise(mrpEl.textContent);
    }
  } else {
    // Non-Amazon pages: JSON-LD Product.offers.price only, otherwise return null (ADR-025).
    // First ₹ on the page fallback removed.
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
