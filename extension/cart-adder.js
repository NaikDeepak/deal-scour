// Injected into the target platform tab by service-worker.js to add an item (× packs) to cart.
// Never enters credentials or submits payment (ADR-020); stops after adding to cart.
async function addDealScourItemToCart(packs = 1, itemUrl = '') {
  function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }

  const urlToCheck = itemUrl || window.location.href;
  const isProduct = typeof isProductPageUrl === 'function' ? isProductPageUrl(urlToCheck) : true;
  if (!isProduct) {
    return { added: false, reason: 'Search page: pick the product yourself' };
  }

  function findIncrementButton() {
    const candidates = document.querySelectorAll('button, div[role="button"], span[role="button"]');
    for (const el of candidates) {
      if (el.offsetParent === null) continue;
      const text = (el.textContent || '').trim();
      const aria = (el.getAttribute('aria-label') || '').toLowerCase();
      if (text === '+' || aria.includes('increase') || aria.includes('increment') || aria.includes('plus')) {
        return el;
      }
    }
    return null;
  }

  const host = window.location.hostname.toLowerCase();

  // On Amazon product page, set quantity dropdown if present before clicking Add to Cart
  if (host.includes('amazon.in') && packs > 1) {
    const qtySelect = document.querySelector('select#quantity');
    if (qtySelect) {
      qtySelect.value = String(packs);
      qtySelect.dispatchEvent(new Event('change', { bubbles: true }));
      await sleep(250);
    }
  }

  const allCandidates = Array.from(
    document.querySelectorAll(
      'button, input[type="submit"], input[type="button"], div[role="button"], span[role="button"], a[role="button"]',
    ),
  );
  const picker = typeof pickAddButton === 'function' ? pickAddButton : null;
  const addBtn = picker ? picker(allCandidates) : null;

  if (!addBtn) {
    return { added: false, reason: 'Add-to-Cart button not found on page; tab left open for 1-click add' };
  }

  addBtn.click();
  await sleep(700);

  // For quick-commerce / Flipkart steppers when packs > 1
  if (!host.includes('amazon.in') && packs > 1) {
    for (let i = 1; i < packs; i += 1) {
      const plusBtn = findIncrementButton();
      if (plusBtn) {
        plusBtn.click();
        await sleep(450);
      }
    }
  }

  return { added: true, packs };
}

if (typeof module !== 'undefined') {
  module.exports = { addDealScourItemToCart };
}
