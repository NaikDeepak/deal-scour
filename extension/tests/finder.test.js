const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {
  extractCandidates,
  parseHtmlToDom,
  waitForCandidates,
  parsePackLabel,
  isSponsoredAdAlt,
} = require('../finder.js');

const FIXTURES_DIR = path.join(__dirname, 'fixtures');

describe('Case 8: finder.js extractCandidates on search snippets', () => {
  it('extracts <= 5 deduped candidates with price and pack from Amazon search snippet and ignores ads/non-products', () => {
    const html = fs.readFileSync(path.join(FIXTURES_DIR, 'amazon-search.html'), 'utf8');
    const dom = parseHtmlToDom(html, 'https://www.amazon.in/s?k=toor+dal');
    const candidates = extractCandidates(dom);

    assert.equal(candidates.length, 5);
    // Ensure sponsored B09AD00001 and 6th item B08XY56789 are not included
    const urls = candidates.map((c) => c.url);
    assert.ok(!urls.some((u) => u.includes('B09AD00001')));
    assert.ok(!urls.some((u) => u.includes('B08XY56789')));
    assert.ok(!urls.some((u) => u.includes('/s?k=')));

    // First candidate is B07BG5M32L (deduped despite two anchors)
    assert.ok(candidates[0].url.includes('/dp/B07BG5M32L'));
    assert.ok(candidates[0].title.includes('Tata Sampann Unpolished Toor Dal'));
    assert.equal(candidates[0].price_paise, 18900);
    assert.equal(candidates[0].pack_label, '1kg');

    // Second candidate has 500 g -> 500g and ₹98 -> 9800
    assert.ok(candidates[1].url.includes('/dp/B08XY12345'));
    assert.equal(candidates[1].price_paise, 9800);
    assert.equal(candidates[1].pack_label, '500g');
  });

  it('extracts deduped candidates with price and pack from Flipkart search snippet and ignores ads/non-products', () => {
    const html = fs.readFileSync(path.join(FIXTURES_DIR, 'flipkart-search.html'), 'utf8');
    const dom = parseHtmlToDom(html, 'https://www.flipkart.com/search?q=almonds');
    const candidates = extractCandidates(dom);

    assert.equal(candidates.length, 3);
    assert.ok(!candidates.some((c) => c.url.includes('ALMAD00001')));
    assert.ok(!candidates.some((c) => c.url.includes('/search?q=')));

    assert.ok(candidates[0].url.includes('pid=ALM1000001'));
    assert.ok(candidates[0].title.includes('Happilo'));
    assert.equal(candidates[0].price_paise, 44900);
    assert.equal(candidates[0].pack_label, '500g');

    assert.ok(candidates[2].url.includes('pid=ALM1000003'));
    assert.equal(candidates[2].price_paise, 89000);
    assert.equal(candidates[2].pack_label, '1kg');
  });

  it('extracts deduped candidates from Zepto search snippet and ignores ad cards', () => {
    const html = fs.readFileSync(path.join(FIXTURES_DIR, 'zepto-search.html'), 'utf8');
    const dom = parseHtmlToDom(html, 'https://www.zepto.com/search?query=sunflower+seeds');
    const candidates = extractCandidates(dom);

    assert.equal(candidates.length, 3);
    assert.ok(!candidates.some((c) => c.url.includes('c3480d95')));

    assert.equal(candidates[0].title, 'Daily Good Sunflower Seeds');
    assert.equal(candidates[0].price_paise, 3700);
    assert.equal(candidates[0].pack_label, '100g');
    assert.ok(!candidates[0].title.includes('₹'));
    assert.ok(!candidates[0].title.includes('ADD'));

    assert.equal(candidates[1].title, 'Farmley Premium Sunflower Seeds');
    assert.equal(candidates[1].price_paise, 12900);
    assert.equal(candidates[1].pack_label, '250g');
    assert.ok(!candidates[1].title.includes('₹'));
    assert.ok(!candidates[1].title.includes('ADD'));

    assert.equal(candidates[2].title, 'True Elements Roasted Sunflower Seeds');
    assert.equal(candidates[2].price_paise, 7300);
    assert.equal(candidates[2].pack_label, '200g');
    assert.ok(!candidates[2].title.includes('₹'));
    assert.ok(!candidates[2].title.includes('ADD'));
  });
});

describe('Case 3 (Spec): Ad alt matcher', () => {
  it('matches ad alt markers and rejects non-ad alts', () => {
    assert.equal(isSponsoredAdAlt('P3 - Ad.png'), true);
    assert.equal(isSponsoredAdAlt('Badam Giri'), false);
    assert.equal(isSponsoredAdAlt('Add to cart'), false);
    assert.equal(isSponsoredAdAlt('ADD'), false);
  });
});

function createFakeChrome({ completeTabs = true } = {}) {
  const listeners = [];
  const createdTabs = [];
  const removedTabIds = [];
  const executedScripts = [];
  let nextTabId = 100;

  const fakeChrome = {
    runtime: {
      id: 'dealscour-ext-id',
      getURL: (p) => `chrome-extension://dealscour-ext-id/${p}`,
      onMessage: {
        addListener: (fn) => listeners.push(fn),
      },
    },
    windows: {
      onRemoved: {
        addListener: () => {},
      },
    },
    storage: {
      local: {
        set: async () => {},
        remove: async () => {},
      },
    },
    tabs: {
      onUpdated: {
        addListener: (fn) => {
          if (completeTabs) {
            setTimeout(() => {
              const lastTab = createdTabs[createdTabs.length - 1];
              if (lastTab) {
                fn(lastTab.id, { status: 'complete' });
              }
            }, 5);
          }
        },
        removeListener: () => {},
      },
      create: async ({ url, active }) => {
        const id = nextTabId++;
        createdTabs.push({ id, url, active });
        return { id, url, active };
      },
      remove: async (tabId) => {
        removedTabIds.push(tabId);
      },
      sendMessage: async () => {},
    },
    scripting: {
      executeScript: async (opts) => {
        executedScripts.push(opts);
        if (opts.func) {
          return [
            {
              result: [
                {
                  url: 'https://www.amazon.in/dp/B07BG5M32L',
                  title: 'Tata Sampann Unpolished Toor Dal 1kg',
                  price_paise: 18900,
                  pack_label: '1kg',
                },
              ],
            },
          ];
        }
        return [];
      },
    },
    _createdTabs: createdTabs,
    _removedTabIds: removedTabIds,
    _executedScripts: executedScripts,
  };

  return fakeChrome;
}

describe('Case 17: Worker sender check and search URL validation', () => {
  it('ignores wrong origin or foreign sender.id and runs for allowed origin', async () => {
    const fakeChrome = createFakeChrome({ completeTabs: true });
    globalThis.chrome = fakeChrome;
    const { handleRuntimeMessage, resetWorkerStateForTests } = require('../service-worker.js');
    resetWorkerStateForTests();

    // 1. Foreign sender.id -> ignored
    let foreignCalled = false;
    const foreignHandled = handleRuntimeMessage(
      {
        type: 'DEALSCOUR_FIND_PRODUCT',
        catalogId: 1,
        targets: [{ platform: 'amazon', url: 'https://www.amazon.in/s?k=toor' }],
      },
      { id: 'foreign-ext-id', tab: { id: 1, url: 'http://localhost:5173/plans' } },
      () => {
        foreignCalled = true;
      }
    );
    assert.equal(foreignHandled, false);
    assert.equal(foreignCalled, false);
    assert.equal(fakeChrome._createdTabs.length, 0);

    // 2. Disallowed origin -> ignored for both DEALSCOUR_FIND_PRODUCT and DEALSCOUR_RUN_SCOUR
    let badOriginCalled = false;
    const badOriginHandled = handleRuntimeMessage(
      {
        type: 'DEALSCOUR_FIND_PRODUCT',
        catalogId: 1,
        targets: [{ platform: 'amazon', url: 'https://www.amazon.in/s?k=toor' }],
      },
      { id: 'dealscour-ext-id', tab: { id: 1, url: 'https://evil.example.com/plans' } },
      () => {
        badOriginCalled = true;
      }
    );
    assert.equal(badOriginHandled, false);
    assert.equal(badOriginCalled, false);

    const badScourHandled = handleRuntimeMessage(
      {
        type: 'DEALSCOUR_RUN_SCOUR',
        targets: [{ listing_id: 'l-1', platform: 'amazon', url: 'https://www.amazon.in/dp/B07BG5M32L', title: 'Toor' }],
      },
      { id: 'dealscour-ext-id', tab: { id: 1, url: 'https://evil.example.com/plans' } },
      () => {
        badOriginCalled = true;
      }
    );
    assert.equal(badScourHandled, false);
    assert.equal(badOriginCalled, false);
    assert.equal(fakeChrome._createdTabs.length, 0);

    // 3. Allowed origin -> runs, opens valid search URL, refuses product URL or mismatched platform URL
    const response = await new Promise((resolve) => {
      const handled = handleRuntimeMessage(
        {
          type: 'DEALSCOUR_FIND_PRODUCT',
          catalogId: 1,
          delayMs: 0,
          timeoutMs: 100,
          targets: [
            { platform: 'amazon', url: 'https://www.amazon.in/s?k=toor' },
            { platform: 'amazon', url: 'https://www.amazon.in/dp/B07BG5M32L' },
            { platform: 'amazon', url: 'https://www.flipkart.com/search?q=toor' },
          ],
        },
        { id: 'dealscour-ext-id', tab: { id: 1, url: 'http://localhost:5173/' } },
        resolve
      );
      assert.equal(handled, true);
    });

    assert.equal(fakeChrome._createdTabs.length, 1);
    assert.equal(fakeChrome._createdTabs[0].url, 'https://www.amazon.in/s?k=toor');
    assert.equal(response.results.length, 1);
    assert.equal(response.results[0].platform, 'amazon');
  });
});

describe('Case 18: Worker timeout skip and single-find concurrency guard', () => {
  it('on timeout skips executeScript on that tab and removes the tab', async () => {
    const fakeChrome = createFakeChrome({ completeTabs: false });
    globalThis.chrome = fakeChrome;
    const { handleRuntimeMessage, resetWorkerStateForTests } = require('../service-worker.js');
    resetWorkerStateForTests();

    const response = await new Promise((resolve) => {
      handleRuntimeMessage(
        {
          type: 'DEALSCOUR_FIND_PRODUCT',
          catalogId: 2,
          delayMs: 0,
          timeoutMs: 25,
          targets: [{ platform: 'amazon', url: 'https://www.amazon.in/s?k=almonds' }],
        },
        { id: 'dealscour-ext-id', tab: { id: 1, url: 'http://127.0.0.1:8000/' } },
        resolve
      );
    });

    assert.equal(fakeChrome._createdTabs.length, 1);
    assert.equal(fakeChrome._executedScripts.length, 0);
    assert.deepEqual(fakeChrome._removedTabIds, [fakeChrome._createdTabs[0].id]);
    assert.deepEqual(response.results, [
      {
        platform: 'amazon',
        status: 'no_links',
        search_url: 'https://www.amazon.in/s?k=almonds',
      },
    ]);
  });

  it('on executeScript failure reports no_links and removes the tab', async () => {
    const fakeChrome = createFakeChrome({ completeTabs: true });
    fakeChrome.scripting.executeScript = async () => {
      throw new Error('Script injection failed');
    };
    globalThis.chrome = fakeChrome;
    const { handleRuntimeMessage, resetWorkerStateForTests } = require('../service-worker.js');
    resetWorkerStateForTests();

    const response = await new Promise((resolve) => {
      handleRuntimeMessage(
        {
          type: 'DEALSCOUR_FIND_PRODUCT',
          catalogId: 3,
          delayMs: 0,
          timeoutMs: 100,
          targets: [{ platform: 'amazon', url: 'https://www.amazon.in/s?k=almonds' }],
        },
        { id: 'dealscour-ext-id', tab: { id: 1, url: 'http://127.0.0.1:8000/' } },
        resolve
      );
    });

    assert.equal(fakeChrome._createdTabs.length, 1);
    assert.deepEqual(fakeChrome._removedTabIds, [fakeChrome._createdTabs[0].id]);
    assert.deepEqual(response.results, [
      {
        platform: 'amazon',
        status: 'no_links',
        search_url: 'https://www.amazon.in/s?k=almonds',
      },
    ]);
  });

  it('rejects a second DEALSCOUR_FIND_PRODUCT while one is already running', async () => {
    const fakeChrome = createFakeChrome({ completeTabs: false });
    globalThis.chrome = fakeChrome;
    const { handleRuntimeMessage, resetWorkerStateForTests } = require('../service-worker.js');
    resetWorkerStateForTests();

    const firstPromise = new Promise((resolve) => {
      handleRuntimeMessage(
        {
          type: 'DEALSCOUR_FIND_PRODUCT',
          catalogId: 10,
          delayMs: 0,
          timeoutMs: 60,
          targets: [{ platform: 'amazon', url: 'https://www.amazon.in/s?k=cashews' }],
        },
        { id: 'dealscour-ext-id', tab: { id: 1, url: 'http://localhost:8000/' } },
        resolve
      );
    });

    let secondResponse = null;
    handleRuntimeMessage(
      {
        type: 'DEALSCOUR_FIND_PRODUCT',
        catalogId: 11,
        delayMs: 0,
        timeoutMs: 60,
        targets: [{ platform: 'flipkart', url: 'https://www.flipkart.com/search?q=cashews' }],
      },
      { id: 'dealscour-ext-id', tab: { id: 1, url: 'http://localhost:8000/' } },
      (res) => {
        secondResponse = res;
      }
    );

    assert.deepEqual(secondResponse, { ok: false, error: 'A search is already running.' });
    await firstPromise;
  });
});

describe('Case 2 (Spec): Pack parsing rules', () => {
  it('parses "200 Gram (Pack Of 2)" -> 400g', () => {
    assert.equal(parsePackLabel('200 Gram (Pack Of 2)'), '400g');
  });

  it('parses "Pack of 3 x 200g" -> 600g', () => {
    assert.equal(parsePackLabel('Pack of 3 x 200g'), '600g');
  });

  it('parses "1 Kg" -> 1kg', () => {
    assert.equal(parsePackLabel('1 Kg'), '1kg');
  });

  it('parses "Premium Walnuts" -> null', () => {
    assert.equal(parsePackLabel('Premium Walnuts'), null);
  });

  it('parses "500gm" -> 500g', () => {
    assert.equal(parsePackLabel('500gm'), '500g');
  });
});

describe('Case 1 (Spec): waitForCandidates with polling and timeout', () => {
  it('fake DOM that gets product links 1.5s after "complete" -> found', async () => {
    const startTime = Date.now();
    let hasLinks = false;
    setTimeout(() => {
      hasLinks = true;
    }, 1500);

    const fakeDom = {
      baseURI: 'https://www.zepto.com/search?query=walnuts',
      querySelectorAll(sel) {
        if (sel === 'a[href]' && hasLinks) {
          return [
            {
              tagName: 'A',
              href: 'https://www.zepto.com/pvid/walnuts-200g-12345',
              textContent: 'Happilo Walnuts 200g',
              parentElement: {
                textContent: 'Happilo Walnuts 200g ₹299',
                querySelectorAll: () => [],
                parentElement: null,
              },
            },
          ];
        }
        return [];
      },
    };

    const res = await waitForCandidates(fakeDom, { timeoutMs: 4000, pollIntervalMs: 250 });
    assert.equal(res.status, 'found');
    assert.equal(res.candidates.length, 1);
    assert.equal(res.candidates[0].pack_label, '200g');
    assert.ok(Date.now() - startTime >= 1400);
  });

  it('fake DOM with no product links after 8s -> no_links', async () => {
    const emptyDom = {
      baseURI: 'https://blinkit.com/s/?q=walnuts',
      querySelectorAll() {
        return [];
      },
    };

    // Use small timeout for test speed, verify status is 'no_links'
    const res = await waitForCandidates(emptyDom, { timeoutMs: 100, pollIntervalMs: 25 });
    assert.equal(res.status, 'no_links');
    assert.deepEqual(res.candidates, []);
  });
});

describe('Case 2 (Spec): Worker returns no_links for 0 candidate shops', () => {
  it('returns {platform, status: "no_links", search_url} when shop has 0 candidates', async () => {
    const fakeChrome = createFakeChrome({ completeTabs: true });
    // Override executeScript to return empty candidates / no_links
    fakeChrome.scripting.executeScript = async (opts) => {
      fakeChrome._executedScripts.push(opts);
      if (opts.func) {
        return [{ result: { status: 'no_links', candidates: [] } }];
      }
      return [];
    };
    globalThis.chrome = fakeChrome;
    const { handleRuntimeMessage, resetWorkerStateForTests } = require('../service-worker.js');
    resetWorkerStateForTests();

    const response = await new Promise((resolve) => {
      handleRuntimeMessage(
        {
          type: 'DEALSCOUR_FIND_PRODUCT',
          catalogId: 1,
          delayMs: 0,
          timeoutMs: 100,
          targets: [{ platform: 'blinkit', url: 'https://blinkit.com/s/?q=walnuts' }],
        },
        { id: 'dealscour-ext-id', tab: { id: 1, url: 'http://localhost:5173/' } },
        resolve
      );
    });

    assert.equal(response.ok, true);
    assert.equal(response.results.length, 1);
    assert.deepEqual(response.results[0], {
      platform: 'blinkit',
      status: 'no_links',
      search_url: 'https://blinkit.com/s/?q=walnuts',
    });
  });
});

