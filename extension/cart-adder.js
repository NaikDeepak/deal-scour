// Injected into the target platform tab by service-worker.js to add an item (× packs) to cart.
// Never enters credentials or submits payment (ADR-020); stops after adding to cart.
async function addDealScourItemToCart(packs = 1, itemUrl = '') {
  function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }

  // Fail closed if lib.js helpers are missing
  if (
    typeof isMatchingProductPage !== 'function' ||
    typeof isProductPageUrl !== 'function' ||
    typeof pickAddButton !== 'function'
  ) {
    return { added: false, reason: 'Extension library helpers not loaded' };
  }

  // Check the page landed on, not just the link (Round 2, Item 15)
  const landedUrl = window.location.href;
  if (!isProductPageUrl(landedUrl)) {
    return { added: false, reason: 'Search page: pick the product yourself' };
  }
  if (!isMatchingProductPage(itemUrl, landedUrl)) {
    return { added: false, reason: 'The shop showed a different page' };
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
  const addBtn = pickAddButton(allCandidates);

  if (!addBtn) {
    return { added: false, reason: 'Add-to-Cart button not found on page; tab left open for 1-click add' };
  }

  addBtn.click();
  await sleep(700);

  // No "+" clicking (Round 2, Item 16): add once and tell user to set remaining packs
  if (!host.includes('amazon.in') && packs > 1) {
    return {
      added: true,
      packs_added: 1,
      packs,
      reason: `Set the quantity to ${packs} yourself`,
    };
  }

  return { added: true, packs };
}

if (typeof module !== 'undefined') {
  module.exports = { addDealScourItemToCart };
}
