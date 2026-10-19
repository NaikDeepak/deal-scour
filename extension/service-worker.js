// DealScour MV3 Background Service Worker
// Handles:
// 1. DEALSCOUR_RUN_SCOUR: Sequential background tab price extraction across supported portals
// 2. DEALSCOUR_RUN_ADD_TO_CART: Requires user click inside confirmation popup (confirm.html) before adding
// 3. DEALSCOUR_FIND_PRODUCT: Sequential background tab search candidate extraction

if (typeof importScripts === 'function') {
  importScripts('lib.js');
} else if (typeof require === 'function') {
  Object.assign(globalThis, require('./lib.js'));
}

const lastOpenTimeByHost = new Map();
const notificationUrls = new Map();
let pendingCart = null;
let findRunning = false;

function resetWorkerStateForTests() {
  lastOpenTimeByHost.clear();
  notificationUrls.clear();
  pendingCart = null;
  findRunning = false;
}

function registerNotificationUrlForTests(notificationId, url) {
  notificationUrls.set(notificationId, url);
}

function isAllowedPortalSender(sender) {
  try {
    if (!sender || !globalThis.chrome || sender.id !== globalThis.chrome.runtime.id) {
      return false;
    }
    if (!sender.tab || typeof sender.tab.url !== 'string') {
      return false;
    }
    const origin = new URL(sender.tab.url).origin;
    return PORTAL_ORIGINS.includes(origin);
  } catch {
    return false;
  }
}

function isAllowedTelegramSender(sender) {
  try {
    if (!sender || !globalThis.chrome || sender.id !== globalThis.chrome.runtime.id) {
      return false;
    }
    if (!sender.tab || typeof sender.tab.url !== 'string') {
      return false;
    }
    const parsed = new URL(sender.tab.url);
    return parsed.protocol === 'https:' && parsed.hostname.toLowerCase() === 'web.telegram.org';
  } catch {
    return false;
  }
}

function resolveRadarApiOrigin(candidate) {
  if (typeof candidate === 'string' && PORTAL_ORIGINS.includes(candidate)) {
    return candidate;
  }
  return typeof DEALSCOUR_API_ORIGIN === 'string' ? DEALSCOUR_API_ORIGIN : 'http://localhost:8000';
}

async function syncRadarChannels() {
  try {
    if (!globalThis.chrome || !globalThis.chrome.storage || typeof globalThis.fetch !== 'function') {
      return [];
    }
    const stored = await globalThis.chrome.storage.local.get(['radarToken', 'radarApiOrigin']);
    const token = stored && typeof stored.radarToken === 'string' ? stored.radarToken.trim() : '';
    if (!token) return [];
    const apiOrigin = resolveRadarApiOrigin(stored && stored.radarApiOrigin);
    const resp = await globalThis.fetch(`${apiOrigin}/api/v1/radar/channels`, {
      method: 'GET',
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!resp || !resp.ok) return [];
    const data = await resp.json();
    const peerIds = Array.isArray(data && data.peer_ids)
      ? data.peer_ids
      : Array.isArray(data && data.channels)
        ? data.channels.filter((c) => c && c.enabled).map((c) => String(c.peer_id))
        : [];
    await globalThis.chrome.storage.local.set({ radarAllowedPeers: peerIds });
    return peerIds;
  } catch {
    return [];
  }
}

async function pollRadarAlerts() {
  try {
    if (!globalThis.chrome || !globalThis.chrome.storage || typeof globalThis.fetch !== 'function') {
      return;
    }
    const stored = await globalThis.chrome.storage.local.get([
      'radarToken',
      'radarApiOrigin',
      'radarLastAlertId',
    ]);
    const token = stored && typeof stored.radarToken === 'string' ? stored.radarToken.trim() : '';
    if (!token) return;
    const apiOrigin = resolveRadarApiOrigin(stored && stored.radarApiOrigin);
    const sinceParam =
      stored && stored.radarLastAlertId ? `?since=${encodeURIComponent(String(stored.radarLastAlertId))}` : '';
    const resp = await globalThis.fetch(`${apiOrigin}/api/v1/radar/alerts${sinceParam}`, {
      method: 'GET',
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!resp || !resp.ok) return;
    const data = await resp.json();
    const alerts = Array.isArray(data && data.alerts) ? data.alerts : [];
    let maxId = stored && typeof stored.radarLastAlertId === 'number' ? stored.radarLastAlertId : 0;

    for (const alert of alerts) {
      if (!alert || typeof alert.url !== 'string') continue;
      if (typeof alert.id === 'number' && alert.id > maxId) {
        maxId = alert.id;
      }
      if (!isAllowedUrl(alert.url) || !isProductPageUrl(alert.url)) {
        continue;
      }
      const notifId = `dealscour-alert-${alert.id || Date.now()}`;
      notificationUrls.set(notifId, alert.url);
      if (globalThis.chrome.notifications && typeof globalThis.chrome.notifications.create === 'function') {
        const rupees = Math.round((Number(alert.price_paise) || 0) / 100);
        await globalThis.chrome.notifications.create(notifId, {
          type: 'basic',
          iconUrl: 'icon.png',
          title: `DealScour: ₹${rupees} — ${alert.title || 'Deal Alert'}`,
          message: Array.isArray(alert.reasons) ? alert.reasons.join(', ') : 'Tap to open product page',
        });
      }
    }

    if (maxId > 0) {
      await globalThis.chrome.storage.local.set({ radarLastAlertId: maxId });
    }
  } catch {
    // ignore polling errors
  }
}

async function handleNotificationClicked(notificationId) {
  const url = notificationUrls.get(notificationId);
  if (!url || !isAllowedUrl(url) || !isProductPageUrl(url)) {
    return false;
  }
  if (globalThis.chrome && globalThis.chrome.tabs && typeof globalThis.chrome.tabs.create === 'function') {
    await globalThis.chrome.tabs.create({ url, active: true });
    return true;
  }
  return false;
}

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
    let timer = null;
    const finish = (status) => {
      if (settled) return;
      settled = true;
      if (timer !== null) {
        clearTimeout(timer);
      }
      globalThis.chrome.tabs.onUpdated.removeListener(listener);
      resolve(status);
    };
    const listener = (updatedId, changeInfo) => {
      if (updatedId === tabId && changeInfo && changeInfo.status === 'complete') {
        finish('complete');
      }
    };
    globalThis.chrome.tabs.onUpdated.addListener(listener);
    timer = setTimeout(() => finish('timeout'), timeoutMs);
  });
}

async function scourSingleTarget(target) {
  let tabId = null;
  try {
    await throttleHost(target.url);
    const createdTab = await globalThis.chrome.tabs.create({ url: target.url, active: false });
    tabId = createdTab.id;
    if (!tabId) {
      return { listing_id: target.listing_id, ok: false, error: 'Failed to create background tab' };
    }

    const tabStatus = await waitForTabComplete(tabId, 12000);
    if (tabStatus === 'timeout') {
      return { listing_id: target.listing_id, ok: false, error: 'Page load timed out' };
    }
    await globalThis.chrome.scripting.executeScript({
      target: { tabId },
      files: ['lib.js', 'extractors.js'],
    });
    const injectionResults = await globalThis.chrome.scripting.executeScript({
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
        await globalThis.chrome.tabs.remove(tabId);
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
    const createdTab = await globalThis.chrome.tabs.create({ url: item.url, active: isLastItem });
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
    await globalThis.chrome.scripting.executeScript({
      target: { tabId },
      files: ['lib.js', 'cart-adder.js'],
    });
    const packs = Number(item.packs) > 0 ? Number(item.packs) : 1;
    const injectionResults = await globalThis.chrome.scripting.executeScript({
      target: { tabId },
      func: (p, u) =>
        typeof addDealScourItemToCart === 'function' ? addDealScourItemToCart(p, u) : { added: false },
      args: [packs, item.url],
    });
    const res = injectionResults && injectionResults[0] ? injectionResults[0].result : { added: false };
    if (res && res.added && !isLastItem) {
      try {
        await globalThis.chrome.tabs.remove(tabId);
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

function isFromPendingConfirmWindow(message, sender) {
  if (!pendingCart || message.requestId !== pendingCart.id) return false;
  const confirmUrl = globalThis.chrome.runtime.getURL('confirm.html');
  if (!sender || sender.id !== globalThis.chrome.runtime.id || !sender.url || !sender.url.startsWith(confirmUrl)) {
    return false;
  }
  return !sender.tab || sender.tab.windowId === pendingCart.windowId;
}

async function clearPendingStorage() {
  try {
    await globalThis.chrome.storage.local.remove(['pendingCartItems', 'pendingCartId']);
  } catch {
    // ignore
  }
}

async function executePendingAddToCart() {
  if (!pendingCart) return;
  const { items, senderTabId, sendResponse } = pendingCart;
  pendingCart = null;
  void clearPendingStorage();

  const results = [];
  for (let i = 0; i < items.length; i += 1) {
    const item = items[i];
    if (senderTabId) {
      try {
        await globalThis.chrome.tabs.sendMessage(senderTabId, {
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
      await globalThis.chrome.tabs.sendMessage(senderTabId, {
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
  void clearPendingStorage();

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
      globalThis.chrome.tabs.sendMessage(senderTabId, {
        type: 'DEALSCOUR_ADD_TO_CART_COMPLETE',
        results,
      });
    } catch {
      // ignore
    }
  }
}

function handleRuntimeMessage(message, sender, sendResponse) {
  if (!message || typeof message.type !== 'string') {
    return false;
  }

  if (message.type === 'DEALSCOUR_CONFIRMED_ADD_TO_CART' || message.type === 'DEALSCOUR_CANCELLED_ADD_TO_CART') {
    if (!isFromPendingConfirmWindow(message, sender)) {
      sendResponse({ ok: false, reason: 'This request has expired. Start again from DealScour.' });
      return true;
    }
    if (message.type === 'DEALSCOUR_CANCELLED_ADD_TO_CART') {
      cancelPendingAddToCart('Cancelled in extension popup');
      sendResponse({ ok: true });
      return true;
    }
    (async () => {
      sendResponse({ ok: true });
      await executePendingAddToCart();
    })();
    return true;
  }

  if (message.type === 'DEALSCOUR_RUN_SCOUR') {
    if (!isAllowedPortalSender(sender)) {
      return false;
    }
    (async () => {
      const allTargets = Array.isArray(message.targets) ? message.targets : [];
      const targets = allTargets.slice(0, 15);
      const results = [];
      await globalThis.chrome.storage.local.set({ lastScourCount: targets.length });

      for (let i = 0; i < targets.length; i += 1) {
        const target = targets[i];
        if (sender.tab && sender.tab.id) {
          try {
            await globalThis.chrome.tabs.sendMessage(sender.tab.id, {
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
    if (!isAllowedPortalSender(sender)) {
      return false;
    }
    (async () => {
      const allItems = Array.isArray(message.items) ? message.items : [];
      const items = allItems.slice(0, 15);
      if (pendingCart) {
        sendResponse({
          results: items.map((it) => ({
            title: it.title,
            platform: it.platform,
            added: false,
            reason: 'Another add-to-cart is waiting for you to confirm it',
          })),
        });
        return;
      }
      const requestId = crypto.randomUUID();
      await globalThis.chrome.storage.local.set({
        pendingCartItems: items,
        pendingCartId: requestId,
        lastCartItemCount: items.length,
      });

      try {
        const win = await globalThis.chrome.windows.create({
          url: `confirm.html?id=${requestId}`,
          type: 'popup',
          width: 420,
          height: 520,
          focused: true,
        });

        pendingCart = {
          id: requestId,
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

  if (message.type === 'DEALSCOUR_FIND_PRODUCT') {
    if (!isAllowedPortalSender(sender)) {
      return false;
    }
    if (findRunning) {
      sendResponse({ ok: false, error: 'A search is already running.' });
      return true;
    }

    findRunning = true;
    (async () => {
      try {
        const allTargets = Array.isArray(message.targets) ? message.targets : [];
        const targets = allTargets.slice(0, 5);
        const delayMs = typeof message.delayMs === 'number' ? message.delayMs : 3000;
        const timeoutMs = typeof message.timeoutMs === 'number' ? message.timeoutMs : 20000;
        const results = [];

        for (let i = 0; i < targets.length; i += 1) {
          const target = targets[i];
          if (!target || !isAllowedSearchUrl(target.url, target.platform)) {
            continue;
          }
          if (i > 0 && delayMs > 0) {
            await sleep(delayMs);
          }

          if (sender.tab && sender.tab.id) {
            try {
              await globalThis.chrome.tabs.sendMessage(sender.tab.id, {
                type: 'DEALSCOUR_FIND_PROGRESS',
                catalogId: message.catalogId,
                current: i + 1,
                total: targets.length,
                platform: target.platform,
                found: 0,
                status: 'searching',
              });
            } catch {
              // portal tab may have closed
            }
          }

          let tabId = null;
          let shopCandidates = [];
          try {
            const createdTab = await globalThis.chrome.tabs.create({ url: target.url, active: false });
            tabId = createdTab.id;
            if (tabId) {
              const tabStatus = await waitForTabComplete(tabId, timeoutMs);
              if (tabStatus === 'complete') {
                await globalThis.chrome.scripting.executeScript({
                  target: { tabId },
                  files: ['lib.js', 'finder.js'],
                });
                const injectionResults = await globalThis.chrome.scripting.executeScript({
                  target: { tabId },
                  func: () => (typeof extractCandidates === 'function' ? extractCandidates(document) : []),
                });
                const extracted =
                  injectionResults && injectionResults[0] && Array.isArray(injectionResults[0].result)
                    ? injectionResults[0].result
                    : [];
                shopCandidates = extracted.slice(0, 5).map((c) => ({
                  platform: target.platform,
                  url: c.url,
                  title: c.title,
                  price_paise: c.price_paise ?? null,
                  pack_label: c.pack_label ?? null,
                }));
              }
            }
          } catch {
            shopCandidates = [];
          } finally {
            if (tabId !== null) {
              try {
                await globalThis.chrome.tabs.remove(tabId);
              } catch {
                // tab may already be closed
              }
            }
          }

          results.push(...shopCandidates);

          if (sender.tab && sender.tab.id) {
            try {
              await globalThis.chrome.tabs.sendMessage(sender.tab.id, {
                type: 'DEALSCOUR_FIND_PROGRESS',
                catalogId: message.catalogId,
                current: i + 1,
                total: targets.length,
                platform: target.platform,
                found: shopCandidates.length,
                status: 'done',
              });
            } catch {
              // ignore
            }
          }
        }

        sendResponse({ ok: true, results });
      } finally {
        findRunning = false;
      }
    })();
    return true;
  }

  if (message.type === 'DEALSCOUR_SET_RADAR_TOKEN') {
    if (!isAllowedPortalSender(sender)) {
      return false;
    }
    const token = typeof message.token === 'string' ? message.token.trim() : '';
    if (!token) {
      sendResponse({ ok: false, error: 'Empty token' });
      return true;
    }
    const apiOrigin = resolveRadarApiOrigin(DEALSCOUR_API_ORIGIN);
    (async () => {
      try {
        await globalThis.chrome.storage.local.set({
          radarToken: token,
          radarApiOrigin: apiOrigin,
        });
        if (globalThis.chrome.alarms && typeof globalThis.chrome.alarms.create === 'function') {
          globalThis.chrome.alarms.create('dealscour-radar-poll', { periodInMinutes: 2 });
        }
        await syncRadarChannels();
        sendResponse({ ok: true });
      } catch (err) {
        sendResponse({ ok: false, error: err instanceof Error ? err.message : String(err) });
      }
    })();
    return true;
  }

  if (message.type === 'DEALSCOUR_RADAR_POSTS') {
    if (!isAllowedTelegramSender(sender)) {
      return false;
    }
    (async () => {
      try {
        const stored = await globalThis.chrome.storage.local.get(['radarToken', 'radarApiOrigin']);
        const token = stored && typeof stored.radarToken === 'string' ? stored.radarToken.trim() : '';
        if (!token) {
          sendResponse({ ok: false, error: 'Radar token not configured' });
          return;
        }
        const apiOrigin = resolveRadarApiOrigin(stored && stored.radarApiOrigin);
        const posts = Array.isArray(message.posts) ? message.posts.slice(0, 50) : [];
        const resp = await globalThis.fetch(`${apiOrigin}/api/v1/radar/posts`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ posts }),
        });
        if (!resp || !resp.ok) {
          sendResponse({ ok: false, status: resp ? resp.status : 0 });
          return;
        }
        const data = await resp.json();
        if (data && data.alerts_created > 0) {
          await pollRadarAlerts();
        }
        sendResponse({ ok: true, ...data });
      } catch (err) {
        sendResponse({ ok: false, error: err instanceof Error ? err.message : String(err) });
      }
    })();
    return true;
  }

  return false;
}

if (typeof chrome !== 'undefined' && chrome.windows && chrome.windows.onRemoved) {
  chrome.windows.onRemoved.addListener((windowId) => {
    if (pendingCart && pendingCart.windowId === windowId) {
      cancelPendingAddToCart('Confirmation window closed');
    }
  });
}

if (typeof chrome !== 'undefined' && chrome.alarms && chrome.alarms.onAlarm) {
  chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm && alarm.name === 'dealscour-radar-poll') {
      void syncRadarChannels();
      void pollRadarAlerts();
    }
  });
}

if (typeof chrome !== 'undefined' && chrome.notifications && chrome.notifications.onClicked) {
  chrome.notifications.onClicked.addListener((notificationId) => {
    void handleNotificationClicked(notificationId);
  });
}

if (typeof chrome !== 'undefined' && chrome.runtime && chrome.runtime.onMessage) {
  chrome.runtime.onMessage.addListener(handleRuntimeMessage);
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    handleRuntimeMessage,
    handleNotificationClicked,
    registerNotificationUrlForTests,
    syncRadarChannels,
    pollRadarAlerts,
    waitForTabComplete,
    isAllowedPortalSender,
    isAllowedTelegramSender,
    resetWorkerStateForTests,
  };
}
