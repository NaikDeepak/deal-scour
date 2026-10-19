// DealScour Add to Cart Confirmation Popup
document.addEventListener('DOMContentLoaded', async () => {
  const itemList = document.getElementById('itemList');
  const confirmBtn = document.getElementById('confirmBtn');
  const cancelBtn = document.getElementById('cancelBtn');

  const requestId = new URLSearchParams(window.location.search).get('id') || '';
  let items = [];
  try {
    const data = await chrome.storage.local.get(['pendingCartItems', 'pendingCartId']);
    if (requestId && data.pendingCartId === requestId && Array.isArray(data.pendingCartItems)) {
      items = data.pendingCartItems;
    }
  } catch {
    items = [];
  }

  if (items.length === 0) {
    itemList.textContent = 'No pending items to add.';
    confirmBtn.disabled = true;
    return;
  }

  confirmBtn.textContent = `Add ${items.length} item${items.length === 1 ? '' : 's'}`;
  itemList.innerHTML = '';

  for (const item of items) {
    const row = document.createElement('div');
    row.className = 'item';

    const badge = document.createElement('span');
    badge.className = 'item-badge';
    badge.textContent = item.platform || 'shop';

    const title = document.createElement('span');
    title.className = 'item-title';
    title.textContent = item.title || item.listing_id || 'Product';

    const packs = document.createElement('span');
    packs.className = 'item-packs';
    const count = Number(item.packs) > 0 ? Number(item.packs) : 1;
    packs.textContent = `${count} ×`;

    row.appendChild(badge);
    row.appendChild(title);
    row.appendChild(packs);
    itemList.appendChild(row);
  }

  let answered = false;

  confirmBtn.addEventListener('click', async () => {
    if (answered) return;
    answered = true;
    confirmBtn.disabled = true;
    confirmBtn.textContent = 'Starting…';
    let res = null;
    try {
      res = await chrome.runtime.sendMessage({ type: 'DEALSCOUR_CONFIRMED_ADD_TO_CART', requestId });
    } catch {
      res = null;
    }
    if (!res || !res.ok) {
      itemList.textContent = (res && res.reason) || 'This request has expired. Start again from DealScour.';
      confirmBtn.textContent = 'Expired';
      return;
    }
    window.close();
  });

  cancelBtn.addEventListener('click', async () => {
    if (answered) return;
    answered = true;
    try {
      await chrome.runtime.sendMessage({ type: 'DEALSCOUR_CANCELLED_ADD_TO_CART', requestId });
    } catch {
      // ignore
    }
    window.close();
  });
});
