// DealScour MV3 Background Service Worker
// Sequentially opens a background tab for each scour target URL, extracts live price, and closes the tab.

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
    const createdTab = await chrome.tabs.create({ url: target.url, active: false });
    tabId = createdTab.id;
    if (!tabId) {
      return { listing_id: target.listing_id, ok: false, error: 'Failed to create background tab' };
    }

    await waitForTabComplete(tabId, 12000);
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ['extractors.js'],
    });
    const injectionResults = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => (typeof extractDealScourPriceFromDOM === 'function' ? extractDealScourPriceFromDOM() : null),
    });

    const extracted = injectionResults && injectionResults[0] ? injectionResults[0].result : null;
    if (!extracted || !extracted.listed_paise) {
      return { listing_id: target.listing_id, ok: false, error: 'Price not found on page' };
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

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || message.type !== 'DEALSCOUR_RUN_SCOUR') {
    return false;
  }

  (async () => {
    const targets = Array.isArray(message.targets) ? message.targets : [];
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
      const res = await scourSingleTarget(target);
      results.push(res);
    }

    sendResponse({ results });
  })();

  return true;
});
