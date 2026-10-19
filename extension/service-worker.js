// DealScour MV3 Background Service Worker
// Handles:
// 1. DEALSCOUR_RUN_SCOUR: Sequential background tab price extraction across supported portals
// 2. DEALSCOUR_RUN_ADD_TO_CART: Requires user click inside confirmation popup (confirm.html) before adding

importScripts('lib.js');

const lastOpenTimeByHost = new Map();
let pendingCart = null;

async function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function throttleHost(urlStr) {
  try {
    const parsed = new URL(urlStr);
    const host = parsed.hostname.toLowerCase();
    const now = Date.now();
    const lastTime = lastOpenTimeByHost.get(host) || 0;
    const elapsed = now - lastTime;
    if (elapsed < 8000) {
      await sleep(8000 - elapsed);
    }
    lastOpenTimeByHost.set(host, Date.now());
  } catch {
    // ignore parse error
  }
}

async function waitForTabComplete(tabId, timeoutMs = 12000) {
  return new Promise((resolve) => {
    let settled = false;
    const done = () => {
      if (settled) return;
      settled = true;
      chrome.tabs.onUpdated.removeListener(listener);
      resolve();
    };
    const listener = (updatedId, changeInfo) => {
      if (updatedId === tabId && changeInfo.status === 'complete') {
        done();
      }
    };
    chrome.tabs.onUpdated.addListener(listener);
    setTimeout(done, timeoutMs);
  });
}

async function scourSingleTarget(target) {
  let tabId = null;
  try {
    await throttleHost(target.url);
    const createdTab = await chrome.tabs.create({ url: target.url, active: false });
    tabId = createdTab.id;
    if (!tabId) {
      return { listing_id: target.listing_id, ok: false, error: 'Failed to create background tab' };
    }

    await waitForTabComplete(tabId, 12000);
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ['lib.js', 'extractors.js'],
    });
    const injectionResults = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => (typeof extractDealScourPriceFromDOM === 'function' ? extractDealScourPriceFromDOM() : null),
    });

    const extracted = injectionResults && injectionResults[0] ? injectionResults[0].result : null;
    if (!extracted || !extracted.listed_paise) {
      return { listing_id: target.listing_id, ok: false, error: "Couldn't read the price on this page" };
    }
    return {
      listing_id: target.listing_id,
      ok: true,
      ...extracted,
    };
  } catch (err) {
    return {
      listing_id: target.listing_id,
      ok: false,
      error: err instanceof Error ? err.message : String(err),
    };
  } finally {
    if (tabId !== null) {
      try {
        await chrome.tabs.remove(tabId);
      } catch {
        // tab may already be closed
      }
    }
  }
}

async function addSingleItemToCart(item, isLastItem) {
  let tabId = null;
  try {
    await throttleHost(item.url);
    const isProduct = isProductPageUrl(item.url);
    const createdTab = await chrome.tabs.create({ url: item.url, active: isLastItem });
    tabId = createdTab.id;
    if (!tabId) {
      return { title: item.title, platform: item.platform, added: false, reason: 'Failed to open tab' };
    }

    if (!isProduct) {
      return {
        title: item.title,
        platform: item.platform,
        added: false,
        reason: 'Search page: pick the product yourself',
      };
    }

    await waitForTabComplete(tabId, 12000);
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ['lib.js', 'cart-adder.js'],
    });
    const packs = Number(item.packs) > 0 ? Number(item.packs) : 1;
    const injectionResults = await chrome.scripting.executeScript({
      target: { tabId },
      func: (p, u) =>
        typeof addDealScourItemToCart === 'function' ? addDealScourItemToCart(p, u) : { added: false },
      args: [packs, item.url],
    });
    const res = injectionResults && injectionResults[0] ? injectionResults[0].result : { added: false };
    if (res && res.added && !isLastItem) {
      try {
        await chrome.tabs.remove(tabId);
      } catch {
        // ignore
      }
    }
    return { title: item.title, platform: item.platform, ...(res || { added: false }) };
  } catch (err) {
    return {
      title: item.title,
      platform: item.platform,
      added: false,
      reason: err instanceof Error ? err.message : String(err),
    };
  }
}

async function executePendingAddToCart() {
  if (!pendingCart) return;
  const { items, senderTabId, sendResponse } = pendingCart;
  pendingCart = null;

  const results = [];
  for (let i = 0; i < items.length; i += 1) {
    const item = items[i];
    if (senderTabId) {
      try {
        await chrome.tabs.sendMessage(senderTabId, {
          type: 'DEALSCOUR_CART_PROGRESS',
          current: i + 1,
          total: items.length,
          platform: item.platform,
          title: item.title,
        });
      } catch {
        // ignore
      }
    }

    if (!isAllowedUrl(item.url)) {
      results.push({
        title: item.title,
        platform: item.platform,
        added: false,
        reason: 'Not a supported shop link',
      });
      continue;
    }

    const isLast = i === items.length - 1;
    const res = await addSingleItemToCart(item, isLast);
    results.push(res);
  }

  if (sendResponse) {
    try {
      sendResponse({ results });
    } catch {
      // ignore
    }
  }

  if (senderTabId) {
    try {
      await chrome.tabs.sendMessage(senderTabId, {
        type: 'DEALSCOUR_ADD_TO_CART_COMPLETE',
        results,
      });
    } catch {
      // ignore
    }
  }
}

function cancelPendingAddToCart(reason = 'Cancelled by user') {
  if (!pendingCart) return;
  const { items, senderTabId, sendResponse } = pendingCart;
  pendingCart = null;

  const results = items.map((it) => ({
    title: it.title,
    platform: it.platform,
    added: false,
    reason,
  }));

  if (sendResponse) {
    try {
      sendResponse({ results });
    } catch {
      // ignore
    }
  }

  if (senderTabId) {
    try {
      chrome.tabs.sendMessage(senderTabId, {
        type: 'DEALSCOUR_ADD_TO_CART_COMPLETE',
        results,
      });
    } catch {
      // ignore
    }
  }
}

chrome.windows.onRemoved.addListener((windowId) => {
  if (pendingCart && pendingCart.windowId === windowId) {
    cancelPendingAddToCart('Confirmation window closed');
  }
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || typeof message.type !== 'string') {
    return false;
  }

  if (message.type === 'DEALSCOUR_CONFIRMED_ADD_TO_CART') {
    (async () => {
      await executePendingAddToCart();
      sendResponse({ ok: true });
    })();
    return true;
  }

  if (message.type === 'DEALSCOUR_CANCELLED_ADD_TO_CART') {
    cancelPendingAddToCart('Cancelled in extension popup');
    sendResponse({ ok: true });
    return true;
  }

  if (message.type === 'DEALSCOUR_RUN_SCOUR') {
    (async () => {
      // Max 15 targets per scour run
      const allTargets = Array.isArray(message.targets) ? message.targets : [];
      const targets = allTargets.slice(0, 15);
      const results = [];
      await chrome.storage.local.set({ lastScourCount: targets.length });

      for (let i = 0; i < targets.length; i += 1) {
        const target = targets[i];
        if (sender.tab && sender.tab.id) {
          try {
            await chrome.tabs.sendMessage(sender.tab.id, {
              type: 'DEALSCOUR_SCOUR_PROGRESS',
              current: i + 1,
              total: targets.length,
              listing_id: target.listing_id,
              platform: target.platform,
              title: target.title,
            });
          } catch {
            // portal tab may have navigated
          }
        }

        // Refuse unsupported shop links
        if (!isAllowedUrl(target.url)) {
          results.push({
            listing_id: target.listing_id,
            ok: false,
            error: 'Not a supported shop link',
          });
          continue;
        }

        const res = await scourSingleTarget(target);
        results.push(res);
      }

      sendResponse({ results });
    })();
    return true;
  }

  if (message.type === 'DEALSCOUR_RUN_ADD_TO_CART') {
    (async () => {
      // Max 15 items per add-to-cart run
      const allItems = Array.isArray(message.items) ? message.items : [];
      const items = allItems.slice(0, 15);
      await chrome.storage.local.set({ pendingCartItems: items, lastCartItemCount: items.length });

      try {
        const win = await chrome.windows.create({
          url: 'confirm.html',
          type: 'popup',
          width: 420,
          height: 520,
          focused: true,
        });

        pendingCart = {
          items,
          senderTabId: sender.tab?.id,
          sendResponse,
          windowId: win.id,
        };
      } catch (err) {
        sendResponse({
          results: items.map((it) => ({
            title: it.title,
            platform: it.platform,
            added: false,
            reason: `Failed to open confirmation popup: ${err instanceof Error ? err.message : String(err)}`,
          })),
        });
      }
    })();
    return true;
  }

  return false;
});
