// Content script for https://web.telegram.org/*
// Reads new posts ONLY when the active chat's peer_id is in the owner's allowed channel list.
// Never reads other chats, never sends names/phones/private messages, and never clicks or types in Telegram.

const seenByRoot = new WeakMap();
const URL_IN_TEXT_RE = /https?:\/\/[^\s<>"')\]*]+/gi;

function normalizePeer(raw) {
  if (!raw || typeof raw !== 'string') return '';
  let s = raw.trim();
  if (s.startsWith('#')) {
    s = s.slice(1).trim();
  }
  return s;
}

function getActivePeerId(rootOrDoc) {
  if (!rootOrDoc || typeof rootOrDoc !== 'object') return '';
  if (typeof rootOrDoc.peerId === 'string') return normalizePeer(rootOrDoc.peerId);
  if (typeof rootOrDoc.peer_id === 'string') return normalizePeer(rootOrDoc.peer_id);
  if (rootOrDoc.location && typeof rootOrDoc.location.hash === 'string') {
    return normalizePeer(rootOrDoc.location.hash);
  }
  if (rootOrDoc.dataset && typeof rootOrDoc.dataset.peerId === 'string') {
    return normalizePeer(rootOrDoc.dataset.peerId);
  }
  if (typeof globalThis.location === 'object' && typeof globalThis.location.hash === 'string') {
    return normalizePeer(globalThis.location.hash);
  }
  return '';
}

function extractLinksFromNode(node, text) {
  const links = [];
  const seen = new Set();

  function addLink(u) {
    if (!u || typeof u !== 'string') return;
    const cleaned = u.trim().replace(/[.,;:!?)>\]*'"]+$/, '');
    if ((cleaned.startsWith('https://') || cleaned.startsWith('http://')) && !seen.has(cleaned)) {
      seen.add(cleaned);
      links.push(cleaned);
    }
  }

  if (Array.isArray(node.links)) {
    for (const l of node.links) addLink(l);
  }

  if (typeof node.querySelectorAll === 'function') {
    const anchors = node.querySelectorAll('a[href]');
    for (const a of Array.from(anchors)) {
      const href = a.href || (typeof a.getAttribute === 'function' ? a.getAttribute('href') : '');
      addLink(href);
    }
  }

  if (typeof text === 'string' && text) {
    const matches = text.match(URL_IN_TEXT_RE) || [];
    for (const m of matches) addLink(m);
  }

  return links;
}

function extractChannelPosts(rootOrDoc, allowedPeers, explicitSeenSet) {
  if (!rootOrDoc || !Array.isArray(allowedPeers) || allowedPeers.length === 0) {
    return [];
  }

  const allowedSet = new Set(allowedPeers.map(normalizePeer).filter(Boolean));
  if (allowedSet.size === 0) {
    return [];
  }

  const activePeer = getActivePeerId(rootOrDoc);
  if (!activePeer || !allowedSet.has(activePeer)) {
    return [];
  }

  let seen = explicitSeenSet;
  if (!seen) {
    seen = seenByRoot.get(rootOrDoc);
    if (!seen) {
      seen = new Set();
      seenByRoot.set(rootOrDoc, seen);
    }
  }

  let rawNodes = [];
  if (Array.isArray(rootOrDoc.messages)) {
    rawNodes = rootOrDoc.messages;
  } else if (Array.isArray(rootOrDoc.posts)) {
    rawNodes = rootOrDoc.posts;
  } else if (typeof rootOrDoc.querySelectorAll === 'function') {
    rawNodes = Array.from(rootOrDoc.querySelectorAll('[data-mid], [data-message-id], .message[data-mid]'));
  }

  const results = [];
  for (const node of rawNodes) {
    if (!node || typeof node !== 'object') continue;

    // If node specifies its own peer_id, verify it matches activePeer
    const nodePeer = normalizePeer(
      node.peer_id ||
        node.peerId ||
        (node.dataset && node.dataset.peerId) ||
        (typeof node.getAttribute === 'function' ? node.getAttribute('data-peer-id') : '') ||
        activePeer
    );
    if (nodePeer !== activePeer) continue;

    const rawId =
      node.message_id ??
      node.id ??
      (node.dataset && (node.dataset.mid || node.dataset.messageId)) ??
      (typeof node.getAttribute === 'function'
        ? node.getAttribute('data-mid') || node.getAttribute('data-message-id')
        : null);

    if (rawId === null || rawId === undefined || String(rawId).trim() === '') continue;
    const messageId = String(rawId).trim();

    const dedupeKey = `${activePeer}:${messageId}`;
    if (seen.has(dedupeKey)) continue;

    let rawText = '';
    if (typeof node.text === 'string') {
      rawText = node.text;
    } else if (typeof node.querySelector === 'function') {
      const msgBody = node.querySelector('.message, .text-content, .translatable-message');
      rawText = (msgBody ? msgBody.textContent : node.textContent) || '';
    } else if (typeof node.textContent === 'string') {
      rawText = node.textContent;
    } else if (typeof node.innerText === 'string') {
      rawText = node.innerText;
    }

    const text = rawText.trim().slice(0, 2000);
    const links = extractLinksFromNode(node, text);
    if (!text && links.length === 0) continue;

    const postedAt =
      node.posted_at ||
      (node.dataset && node.dataset.timestamp) ||
      (typeof node.getAttribute === 'function' ? node.getAttribute('data-timestamp') : null) ||
      new Date().toISOString();

    seen.add(dedupeKey);
    results.push({
      peer_id: activePeer,
      message_id: messageId,
      text,
      links,
      posted_at: String(postedAt),
    });
  }

  return results;
}

async function runReaderTick(rootOrDoc, deps = {}) {
  const getStorage =
    deps.getStorage ||
    (async () => {
      if (typeof chrome !== 'undefined' && chrome.storage && chrome.storage.local) {
        return chrome.storage.local.get(['radarAllowedPeers']);
      }
      return {};
    });

  const sendMessage =
    deps.sendMessage ||
    (async (msg) => {
      if (typeof chrome !== 'undefined' && chrome.runtime && chrome.runtime.sendMessage) {
        return chrome.runtime.sendMessage(msg);
      }
      return null;
    });

  const data = await getStorage();
  const allowedPeers = data && Array.isArray(data.radarAllowedPeers) ? data.radarAllowedPeers : [];
  if (allowedPeers.length === 0) {
    return [];
  }

  const newPosts = extractChannelPosts(rootOrDoc, allowedPeers);
  if (newPosts.length > 0) {
    await sendMessage({
      type: 'DEALSCOUR_RADAR_POSTS',
      posts: newPosts.slice(0, 50),
    });
  }
  return newPosts;
}

if (typeof window !== 'undefined' && typeof document !== 'undefined' && window.location) {
  if (window.location.hostname === 'web.telegram.org') {
    setInterval(() => {
      void runReaderTick(document);
    }, 5000);
    window.addEventListener('hashchange', () => {
      void runReaderTick(document);
    });
  }
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    extractChannelPosts,
    runReaderTick,
    normalizePeer,
  };
}
