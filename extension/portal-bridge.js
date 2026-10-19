// Content script running on the DealScour Web Portal.
// Bridges window.postMessage from the React app to the extension's background service worker.
(() => {
  document.documentElement.setAttribute('data-dealscour-extension', 'installed');
  window.postMessage({ type: 'DEALSCOUR_EXTENSION_READY', version: '0.1.0' }, window.location.origin);

  window.addEventListener('message', async (event) => {
    if (event.source !== window || !event.data || typeof event.data.type !== 'string') {
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
    }
  });

  chrome.runtime.onMessage.addListener((message) => {
    if (message && message.type === 'DEALSCOUR_SCOUR_PROGRESS') {
      window.postMessage(message, window.location.origin);
    }
  });
})();
