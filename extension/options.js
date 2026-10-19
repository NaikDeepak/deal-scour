// Options page script for DealScour extension
async function loadOptions() {
  if (typeof chrome === 'undefined') return;
  const versionEl = document.getElementById('ext-version');
  if (versionEl && chrome.runtime && typeof chrome.runtime.getManifest === 'function') {
    versionEl.textContent = `DealScour extension v${chrome.runtime.getManifest().version}`;
  }
  if (!chrome.storage || !chrome.storage.local) return;
  const data = await chrome.storage.local.get(['radarToken', 'radarApiOrigin', 'radarAllowedPeers']);
  const stateEl = document.getElementById('connection-state');
  const originEl = document.getElementById('api-origin');

  const peers = Array.isArray(data.radarAllowedPeers) ? data.radarAllowedPeers : [];
  if (stateEl) {
    stateEl.textContent = data.radarToken
      ? `Extension connected (${peers.length} enabled channel${peers.length === 1 ? '' : 's'} synced)`
      : 'Not connected — click "Connect extension" on the DealScour Radar tab.';
  }
  if (originEl && data.radarApiOrigin && PORTAL_ORIGINS.includes(data.radarApiOrigin)) {
    originEl.value = data.radarApiOrigin;
  }
}

async function saveOptions() {
  if (typeof chrome === 'undefined' || !chrome.storage || !chrome.storage.local) return;
  const originEl = document.getElementById('api-origin');
  const statusEl = document.getElementById('status-msg');
  const selected = originEl ? originEl.value : DEALSCOUR_API_ORIGIN;
  const validOrigin = PORTAL_ORIGINS.includes(selected) ? selected : DEALSCOUR_API_ORIGIN;
  await chrome.storage.local.set({ radarApiOrigin: validOrigin });
  if (statusEl) {
    statusEl.textContent = 'Saved.';
  }
  await loadOptions();
}

async function disconnectRadar() {
  if (typeof chrome === 'undefined' || !chrome.storage || !chrome.storage.local) return;
  await chrome.storage.local.remove(['radarToken', 'radarAllowedPeers']);
  const statusEl = document.getElementById('status-msg');
  if (statusEl) {
    statusEl.textContent = 'Disconnected.';
  }
  await loadOptions();
}

if (typeof document !== 'undefined') {
  document.addEventListener('DOMContentLoaded', () => {
    void loadOptions();
    const saveBtn = document.getElementById('save-btn');
    if (saveBtn) saveBtn.addEventListener('click', () => void saveOptions());
    const discBtn = document.getElementById('disconnect-btn');
    if (discBtn) discBtn.addEventListener('click', () => void disconnectRadar());
  });
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { loadOptions, saveOptions, disconnectRadar };
}
