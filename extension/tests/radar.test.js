const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const { extractChannelPosts, runReaderTick } = require('../telegram-reader.js');

// Case 8: Extension: extractChannelPosts(dom-like objects, allowedPeers) returns only new posts
// for allowed peers; ignores other chats; strips nothing but text/links/ids.
// Notification click opens the product url only if isAllowedUrl / isProductPageUrl.
describe('Case 8 & 12: telegram-reader.js extractChannelPosts', () => {
  it('Case 12: Reader with no peer list loaded -> sends nothing', async () => {
    const dom = {
      peerId: '-1001191090845',
      messages: [
        {
          id: '501',
          text: 'Loot ₹99 : https://amzn.to/x',
          links: ['https://amzn.to/x'],
          senderName: 'Alice Secret',
          phoneNumber: '+919999999999',
        },
      ],
    };

    assert.deepEqual(extractChannelPosts(dom, null), []);
    assert.deepEqual(extractChannelPosts(dom, undefined), []);
    assert.deepEqual(extractChannelPosts(dom, []), []);

    let sentMessages = 0;
    await runReaderTick(dom, {
      getStorage: async () => ({}),
      sendMessage: async () => {
        sentMessages += 1;
      },
    });
    assert.equal(sentMessages, 0);
  });

  it('Case 8: returns only new posts for allowed peers, ignores other chats, and strips private fields', () => {
    const allowedPeers = ['-1001191090845'];

    // Disallowed chat -> returns []
    const otherChatDom = {
      location: { hash: '#-1009999999999' },
      messages: [
        {
          id: '1',
          text: 'Private chat ₹100 https://amzn.to/priv',
          sender: 'Bob',
          phone: '+918888888888',
        },
      ],
    };
    assert.deepEqual(extractChannelPosts(otherChatDom, allowedPeers), []);

    // Allowed chat -> extracts only {peer_id, message_id, text, links, posted_at}
    const channelDom = {
      location: { hash: '#-1001191090845' },
      messages: [
        {
          id: '101',
          text: 'Loot ₹99 : https://amzn.to/x',
          links: ['https://amzn.to/x'],
          posted_at: '2026-10-19T10:00:00Z',
          authorName: 'Offer Box Admin',
          phoneNumber: '+919999999999',
        },
      ],
    };

    const firstPass = extractChannelPosts(channelDom, allowedPeers);
    assert.equal(firstPass.length, 1);
    assert.deepEqual(Object.keys(firstPass[0]).sort(), [
      'links',
      'message_id',
      'peer_id',
      'posted_at',
      'text',
    ]);
    assert.equal(firstPass[0].peer_id, '-1001191090845');
    assert.equal(firstPass[0].message_id, '101');
    assert.equal(firstPass[0].text, 'Loot ₹99 : https://amzn.to/x');
    assert.deepEqual(firstPass[0].links, ['https://amzn.to/x']);

    // Second pass with one old post (101) and one new post (102) -> returns ONLY new post 102
    channelDom.messages.push({
      id: '102',
      text: 'Whey 1kg @2400 https://link.amazon/y',
      links: ['https://link.amazon/y'],
      posted_at: '2026-10-19T10:05:00Z',
    });

    const secondPass = extractChannelPosts(channelDom, allowedPeers);
    assert.equal(secondPass.length, 1);
    assert.equal(secondPass[0].message_id, '102');
  });
});

describe('Case 8 & 11: service-worker.js radar sender checks and notification click', () => {
  it('Case 11: DEALSCOUR_RADAR_POSTS from a non-telegram tab -> ignored; DEALSCOUR_SET_RADAR_TOKEN from a non-portal origin -> ignored', async () => {
    const store = {
      radarToken: 'valid-token-123',
      radarAllowedPeers: ['-1001191090845'],
    };
    const createdTabs = [];
    const fetchCalls = [];

    globalThis.fetch = async (url, init) => {
      fetchCalls.push({ url, init });
      return {
        ok: true,
        status: 200,
        json: async () => ({ peer_ids: ['-1001191090845'], alerts: [], processed: 1, alerts_created: 0 }),
      };
    };

    globalThis.chrome = {
      runtime: {
        id: 'dealscour-ext-id',
        getURL: (p) => `chrome-extension://dealscour-ext-id/${p}`,
        onMessage: { addListener: () => {} },
      },
      windows: { onRemoved: { addListener: () => {} } },
      alarms: {
        create: () => {},
        onAlarm: { addListener: () => {} },
      },
      notifications: {
        create: async () => {},
        onClicked: { addListener: () => {} },
      },
      storage: {
        local: {
          get: async (keys) => {
            if (Array.isArray(keys)) {
              const out = {};
              for (const k of keys) out[k] = store[k];
              return out;
            }
            return { ...store };
          },
          set: async (obj) => {
            Object.assign(store, obj);
          },
          remove: async () => {},
        },
      },
      tabs: {
        create: async (opts) => {
          createdTabs.push(opts);
          return { id: 1, ...opts };
        },
        onUpdated: { addListener: () => {}, removeListener: () => {} },
        remove: async () => {},
        sendMessage: async () => {},
      },
    };

    delete require.cache[require.resolve('../service-worker.js')];
    const {
      handleRuntimeMessage,
      handleNotificationClicked,
      registerNotificationUrlForTests,
      resetWorkerStateForTests,
    } = require('../service-worker.js');
    resetWorkerStateForTests();

    // 1. DEALSCOUR_RADAR_POSTS from a non-telegram tab -> ignored
    let nonTgResponded = false;
    const nonTgHandled = handleRuntimeMessage(
      {
        type: 'DEALSCOUR_RADAR_POSTS',
        posts: [{ peer_id: '-1001191090845', message_id: '1', text: 'Loot ₹99 : https://amzn.to/x', links: [] }],
      },
      { id: 'dealscour-ext-id', tab: { id: 10, url: 'https://evil.example.com/' } },
      () => {
        nonTgResponded = true;
      }
    );
    assert.equal(nonTgHandled, false);
    assert.equal(nonTgResponded, false);
    assert.equal(fetchCalls.length, 0);

    // 2. DEALSCOUR_SET_RADAR_TOKEN from a non-portal origin -> ignored
    let nonPortalResponded = false;
    const nonPortalHandled = handleRuntimeMessage(
      {
        type: 'DEALSCOUR_SET_RADAR_TOKEN',
        token: 'attacker-token',
      },
      { id: 'dealscour-ext-id', tab: { id: 11, url: 'https://web.telegram.org/k/' } },
      () => {
        nonPortalResponded = true;
      }
    );
    assert.equal(nonPortalHandled, false);
    assert.equal(nonPortalResponded, false);
    assert.equal(store.radarToken, 'valid-token-123');

    // 3. DEALSCOUR_SET_RADAR_TOKEN from PORTAL_ORIGINS -> saved and answers ok
    const setTokenRes = await new Promise((resolve) => {
      const handled = handleRuntimeMessage(
        {
          type: 'DEALSCOUR_SET_RADAR_TOKEN',
          token: 'fresh-portal-token',
        },
        { id: 'dealscour-ext-id', tab: { id: 12, url: 'http://localhost:5173/radar' } },
        resolve
      );
      assert.equal(handled, true);
    });
    assert.deepEqual(setTokenRes, { ok: true });
    assert.equal(store.radarToken, 'fresh-portal-token');

    // 4. DEALSCOUR_RADAR_POSTS from https://web.telegram.org/k/ -> forwarded with Bearer token
    fetchCalls.length = 0;
    const postRes = await new Promise((resolve) => {
      const handled = handleRuntimeMessage(
        {
          type: 'DEALSCOUR_RADAR_POSTS',
          posts: [
            {
              peer_id: '-1001191090845',
              message_id: '101',
              text: 'Loot ₹99 : https://amzn.to/x',
              links: ['https://amzn.to/x'],
              posted_at: '2026-10-19T12:00:00Z',
            },
          ],
        },
        { id: 'dealscour-ext-id', tab: { id: 13, url: 'https://web.telegram.org/k/#-1001191090845' } },
        resolve
      );
      assert.equal(handled, true);
    });
    assert.equal(postRes.ok, true);
    assert.ok(fetchCalls.length >= 1);
    assert.equal(fetchCalls[0].url, 'http://localhost:8000/api/v1/radar/posts');
    assert.equal(fetchCalls[0].init.headers.Authorization, 'Bearer fresh-portal-token');
    // The server's CSRF check applies to every POST under /api/v1, bearer or not.
    assert.equal(fetchCalls[0].init.headers['X-DealScour'], '1');

    // 5. Case 8 & 16: Notification click opens the product url ONLY if isAllowedUrl && isProductPageUrl
    registerNotificationUrlForTests('notif-good', 'https://www.amazon.in/dp/B072HG4WNC');
    registerNotificationUrlForTests('notif-search', 'https://www.amazon.in/s?k=almonds');
    registerNotificationUrlForTests('notif-evil', 'https://evil.example.com/dp/B072HG4WNC');

    await handleNotificationClicked('notif-search');
    await handleNotificationClicked('notif-evil');
    assert.equal(createdTabs.length, 0);

    await handleNotificationClicked('notif-good');
    assert.equal(createdTabs.length, 1);
    assert.equal(createdTabs[0].url, 'https://www.amazon.in/dp/B072HG4WNC');
  });
});

describe('Case 18: visible extension version in manifest, portal-bridge, and options', () => {
  it('reports chrome.runtime.getManifest().version with no hard-coded version and shows it in options', async () => {
    const fs = require('node:fs');
    const path = require('node:path');
    const manifest = require('../manifest.json');
    assert.match(manifest.version, /^\d+\.\d+\.\d+$/);

    const bridgePath = path.join(__dirname, '..', 'portal-bridge.js');
    const bridgeSrc = fs.readFileSync(bridgePath, 'utf8');
    assert.equal(bridgeSrc.includes('0.1.0'), false, 'portal-bridge.js must not hard-code 0.1.0');
    assert.equal(
      bridgeSrc.includes('chrome.runtime.getManifest().version'),
      true,
      'portal-bridge.js must read chrome.runtime.getManifest().version'
    );

    const postedMessages = [];
    const windowListeners = {};
    globalThis.window = {
      location: { origin: 'http://localhost:5173' },
      postMessage: (msg, targetOrigin) => {
        postedMessages.push({ msg, targetOrigin });
      },
      addEventListener: (evt, cb) => {
        windowListeners[evt] = cb;
      },
    };

    const elements = {
      'ext-version': { textContent: '' },
      'connection-state': { textContent: '' },
      'api-origin': { value: 'http://localhost:8000' },
    };
    globalThis.document = {
      documentElement: {
        setAttribute: () => {},
      },
      getElementById: (id) => elements[id] || null,
      addEventListener: () => {},
    };
    globalThis.chrome = {
      runtime: {
        getManifest: () => ({ version: manifest.version }),
        onMessage: { addListener: () => {} },
        sendMessage: async () => ({ ok: true }),
      },
      storage: {
        local: {
          get: async () => ({ radarToken: 'tok', radarAllowedPeers: ['-1001191090845'] }),
          set: async () => {},
          remove: async () => {},
        },
      },
    };

    delete require.cache[require.resolve('../portal-bridge.js')];
    require('../portal-bridge.js');

    assert.equal(postedMessages.length, 1);
    assert.deepEqual(postedMessages[0].msg, {
      type: 'DEALSCOUR_EXTENSION_READY',
      version: manifest.version,
    });

    // Also responds with manifest version when pinged
    await windowListeners.message({
      origin: 'http://localhost:5173',
      source: globalThis.window,
      data: { type: 'DEALSCOUR_PING_EXTENSION' },
    });
    assert.equal(postedMessages.length, 2);
    assert.deepEqual(postedMessages[1].msg, {
      type: 'DEALSCOUR_EXTENSION_READY',
      version: manifest.version,
    });

    // Options page shows "DealScour extension v<manifest version>"
    delete require.cache[require.resolve('../options.js')];
    const { loadOptions } = require('../options.js');
    await loadOptions();
    assert.equal(elements['ext-version'].textContent, `DealScour extension v${manifest.version}`);
  });
});


// Item 21 / 23: after a reload the reader only sends messages newer than the per-peer last sent id.
describe('Case 23: ignore the backlog after an extension reload', () => {
  const PEER = '-1001191090845';
  const makeDom = (ids) => ({
    peerId: PEER,
    messages: ids.map((id) => ({
      id: String(id),
      text: `Loot ₹99 : https://amzn.to/m${id}`,
      links: [`https://amzn.to/m${id}`],
      posted_at: '2026-10-19T10:00:00Z',
    })),
  });
  const makeDeps = (storage, sent, reply = { ok: true }) => ({
    getStorage: async () => ({ ...storage }),
    setStorage: async (values) => {
      Object.assign(storage, values);
    },
    sendMessage: async (msg) => {
      sent.push(msg);
      return reply;
    },
  });

  it('stored last id 120, posts 118-121 -> only 121 is sent and remembered', async () => {
    const storage = { radarAllowedPeers: [PEER], radarLastSentIds: { [PEER]: 120 } };
    const sent = [];
    const dom = makeDom([118, 119, 120, 121]);

    const posts = await runReaderTick(dom, makeDeps(storage, sent));

    assert.deepEqual(
      posts.map((p) => p.message_id),
      ['121']
    );
    assert.equal(sent.length, 1);
    assert.deepEqual(
      sent[0].posts.map((p) => p.message_id),
      ['121']
    );
    assert.equal(storage.radarLastSentIds[PEER], 121);

    // Same DOM again (or a reload with the stored id) -> nothing more is sent.
    await runReaderTick(dom, makeDeps(storage, sent));
    await runReaderTick(makeDom([118, 119, 120, 121]), makeDeps(storage, sent));
    assert.equal(sent.length, 1);
  });

  it('keeps the last id per peer and never moves it backwards', async () => {
    const other = '-1002222222222';
    const storage = {
      radarAllowedPeers: [PEER, other],
      radarLastSentIds: { [PEER]: 200, [other]: 5 },
    };
    const sent = [];

    await runReaderTick(makeDom([150, 201]), makeDeps(storage, sent));

    assert.equal(storage.radarLastSentIds[PEER], 201);
    assert.equal(storage.radarLastSentIds[other], 5);
    assert.deepEqual(
      sent[0].posts.map((p) => p.message_id),
      ['201']
    );
  });

  it('does not advance the last id (and retries) when the worker reports a failure', async () => {
    const storage = { radarAllowedPeers: [PEER], radarLastSentIds: { [PEER]: 120 } };
    const sent = [];
    const dom = makeDom([121]);

    await runReaderTick(dom, makeDeps(storage, sent, { ok: false, status: 503 }));
    assert.equal(storage.radarLastSentIds[PEER], 120);

    await runReaderTick(dom, makeDeps(storage, sent, { ok: true }));
    assert.equal(sent.length, 2);
    assert.equal(storage.radarLastSentIds[PEER], 121);
  });

  it('first run without a stored id sends everything it sees and remembers the newest', async () => {
    const storage = { radarAllowedPeers: [PEER] };
    const sent = [];

    await runReaderTick(makeDom([7, 9, 8]), makeDeps(storage, sent));

    assert.equal(sent[0].posts.length, 3);
    assert.equal(storage.radarLastSentIds[PEER], 9);
  });
});
