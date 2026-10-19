const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { extractCandidates, parseHtmlToDom } = require('../finder.js');

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
});
