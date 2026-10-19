// Content script running on the DealScour Web Portal.
// Bridges window.postMessage from the React app to the extension's background service worker.
(() => {
  const PORTAL_ORIGINS = [
    'http://localhost:8000',
    'http://127.0.0.1:8000',
    'http://localhost:5173',
    'http://127.0.0.1:5173',
  ];

  if (!PORTAL_ORIGINS.includes(window.location.origin)) {
    return;
  }

  document.documentElement.setAttribute('data-dealscour-extension', 'installed');
  window.postMessage({ type: 'DEALSCOUR_EXTENSION_READY', version: '0.1.0' }, window.location.origin);

  window.addEventListener('message', async (event) => {
    if (
      !PORTAL_ORIGINS.includes(window.location.origin) ||
      event.origin !== window.location.origin ||
      event.source !== window ||
      !event.data ||
      typeof event.data.type !== 'string'
    ) {
      return;
    }

    if (event.data.type === 'DEALSCOUR_PING_EXTENSION') {
      window.postMessage({ type: 'DEALSCOUR_EXTENSION_READY', version: '0.1.0' }, window.location.origin);
      return;
    }

    if (event.data.type === 'DEALSCOUR_SCOUR_REQUEST') {
      const targets = Array.isArray(event.data.targets) ? event.data.targets : [];
      try {
        const response = await chrome.runtime.sendMessage({
          type: 'DEALSCOUR_RUN_SCOUR',
          targets,
        });
        window.postMessage(
          {
            type: 'DEALSCOUR_SCOUR_COMPLETE',
            results: (response && response.results) || [],
          },
          window.location.origin
        );
      } catch (err) {
        window.postMessage(
          {
            type: 'DEALSCOUR_SCOUR_ERROR',
            error: err instanceof Error ? err.message : String(err),
          },
          window.location.origin
        );
      }
      return;
    }

    if (event.data.type === 'DEALSCOUR_ADD_TO_CART_REQUEST') {
      const items = Array.isArray(event.data.items) ? event.data.items : [];
      try {
        const response = await chrome.runtime.sendMessage({
          type: 'DEALSCOUR_RUN_ADD_TO_CART',
          items,
        });
        window.postMessage(
          {
            type: 'DEALSCOUR_ADD_TO_CART_COMPLETE',
            results: (response && response.results) || [],
          },
          window.location.origin
        );
      } catch (err) {
        window.postMessage(
          {
            type: 'DEALSCOUR_ADD_TO_CART_ERROR',
            error: err instanceof Error ? err.message : String(err),
          },
          window.location.origin
        );
      }
      return;
    }

    if (event.data.type === 'DEALSCOUR_FIND_PRODUCT') {
      const catalogId = event.data.catalogId;
      const targets = Array.isArray(event.data.targets) ? event.data.targets : [];
      try {
        const response = await chrome.runtime.sendMessage({
          type: 'DEALSCOUR_FIND_PRODUCT',
          catalogId,
          targets,
        });
        if (response && response.ok === false) {
          window.postMessage(
            {
              type: 'DEALSCOUR_FIND_ERROR',
              catalogId,
              error: response.error || 'Search failed',
            },
            window.location.origin
          );
          return;
        }
        window.postMessage(
          {
            type: 'DEALSCOUR_FIND_COMPLETE',
            catalogId,
            results: (response && response.results) || [],
          },
          window.location.origin
        );
      } catch (err) {
        window.postMessage(
          {
            type: 'DEALSCOUR_FIND_ERROR',
            catalogId,
            error: err instanceof Error ? err.message : String(err),
          },
          window.location.origin
        );
      }
    }
  });

  chrome.runtime.onMessage.addListener((message) => {
    if (!PORTAL_ORIGINS.includes(window.location.origin)) {
      return;
    }
    if (
      message &&
      (message.type === 'DEALSCOUR_SCOUR_PROGRESS' ||
        message.type === 'DEALSCOUR_FIND_PROGRESS' ||
        message.type === 'DEALSCOUR_CART_PROGRESS' ||
        message.type === 'DEALSCOUR_ADD_TO_CART_COMPLETE' ||
        message.type === 'DEALSCOUR_ADD_TO_CART_ERROR')
    ) {
      window.postMessage(message, window.location.origin);
    }
  });
})();
