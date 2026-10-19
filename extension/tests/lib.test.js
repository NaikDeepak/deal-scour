const { describe, it } = require('node:test');
const assert = require('node:assert/strict');
const {
  parseRupeesToPaise,
  priceFromJsonLd,
  isAllowedUrl,
  isProductPageUrl,
  extractProductId,
  pickAddButton,
  isMatchingProductPage,
} = require('../lib.js');

describe('Instamart new domain support (instamart.in/p/<slug>-<ID>)', () => {
  it('isProductPageUrl accepts instamart.in/p/...-ID and rejects instamart.in/search', () => {
    assert.equal(
      isProductPageUrl(
        'https://instamart.in/p/tata-sampann-pure-cashews-whole-kaju-nutritious-delicious-T6LJGMXRBD'
      ),
      true
    );
    assert.equal(isProductPageUrl('https://instamart.in/search?query=cashews'), false);
    assert.equal(isProductPageUrl('https://instamart.in/p/no-valid-id-short'), false);
  });

  it('extractProductId extracts trailing uppercase ID from instamart.in/p/<slug>-<ID>', () => {
    assert.equal(
      extractProductId(
        'https://instamart.in/p/tata-sampann-pure-cashews-whole-kaju-nutritious-delicious-T6LJGMXRBD'
      ),
      'T6LJGMXRBD'
    );
    assert.equal(extractProductId('https://www.swiggy.com/instamart/item/ABC12345'), 'ABC12345');
  });
});

describe('Case 4: parseRupeesToPaise', () => {
  it('parses formatted Indian rupee strings to integer paise', () => {
    assert.equal(parseRupeesToPaise('₹1,299.50'), 129950);
    assert.equal(parseRupeesToPaise('₹ 450'), 45000);
    assert.equal(parseRupeesToPaise('1299.50'), 129950);
    assert.equal(parseRupeesToPaise('₹10'), 1000);
  });

  it('returns null for junk or non-positive values', () => {
    assert.equal(parseRupeesToPaise('junk'), null);
    assert.equal(parseRupeesToPaise(''), null);
    assert.equal(parseRupeesToPaise(null), null);
    assert.equal(parseRupeesToPaise(undefined), null);
    assert.equal(parseRupeesToPaise('₹0'), null);
    assert.equal(parseRupeesToPaise('₹-50'), null);
    assert.equal(parseRupeesToPaise('out of stock'), null);
    assert.equal(parseRupeesToPaise('abc 123 def 456'), null);
  });
});

describe('Case 5: priceFromJsonLd', () => {
  it('reads Product offers when offers is an object', () => {
    const jsonStr = JSON.stringify({
      '@context': 'https://schema.org',
      '@type': 'Product',
      name: 'California Almonds 500g',
      offers: {
        '@type': 'Offer',
        price: '450.00',
        priceCurrency: 'INR',
        availability: 'https://schema.org/InStock',
      },
    });
    const res = priceFromJsonLd([jsonStr]);
    assert.ok(res);
    assert.equal(res.listed_paise, 45000);
    assert.equal(res.in_stock, true);
  });

  it('reads Product offers when offers is an array', () => {
    const jsonStr = JSON.stringify({
      '@type': 'Product',
      name: 'Walnut Kernels 500g',
      offers: [
        {
          '@type': 'Offer',
          price: '599',
          availability: 'https://schema.org/OutOfStock',
        },
      ],
    });
    const res = priceFromJsonLd([jsonStr]);
    assert.ok(res);
    assert.equal(res.listed_paise, 59900);
    assert.equal(res.in_stock, false);
  });

  it('ignores malformed JSON and continues', () => {
    const badJson = '{"@type": "Product", unquoted: bad}';
    const goodJson = JSON.stringify({
      '@type': 'Product',
      offers: { price: '299.00' },
    });
    const res = priceFromJsonLd([badJson, goodJson]);
    assert.ok(res);
    assert.equal(res.listed_paise, 29900);
  });

  it('returns null without Product', () => {
    const orgJson = JSON.stringify({
      '@type': 'Organization',
      name: 'Blinkit',
    });
    assert.equal(priceFromJsonLd([orgJson]), null);
    assert.equal(priceFromJsonLd([]), null);
    assert.equal(priceFromJsonLd(['{ malformed only }']), null);
  });
});

describe('Case 6: isAllowedUrl', () => {
  it('accepts allowed https hosts', () => {
    assert.equal(isAllowedUrl('https://amazon.in/dp/B0012345'), true);
    assert.equal(isAllowedUrl('https://www.amazon.in/dp/B0012345'), true);
    assert.equal(isAllowedUrl('https://flipkart.com/product/p/itm123?pid=ABC'), true);
    assert.equal(isAllowedUrl('https://www.flipkart.com/p/itm123'), true);
    assert.equal(isAllowedUrl('https://blinkit.com/prid/12345'), true);
    assert.equal(isAllowedUrl('https://www.swiggy.com/instamart/item/123'), true);
    assert.equal(isAllowedUrl('https://zeptonow.com/pvid/123'), true);
    assert.equal(isAllowedUrl('https://www.zeptonow.com/pvid/123'), true);
    assert.equal(isAllowedUrl('https://zepto.com/pvid/123'), true);
    assert.equal(isAllowedUrl('https://www.zepto.com/pvid/123'), true);
  });

  it('rejects http, spoofed domains, and untrusted hosts', () => {
    assert.equal(isAllowedUrl('http://amazon.in/dp/B0012345'), false);
    assert.equal(isAllowedUrl('http://www.flipkart.com/p/1'), false);
    assert.equal(isAllowedUrl('https://amazon.in.evil.com/dp/B0012345'), false);
    assert.equal(isAllowedUrl('https://evil.com/?u=amazon.in'), false);
    assert.equal(isAllowedUrl('https://google.com'), false);
    assert.equal(isAllowedUrl('https://notrealshop.com'), false);
    assert.equal(isAllowedUrl('not a url'), false);
    assert.equal(isAllowedUrl(''), false);
    assert.equal(isAllowedUrl(null), false);
  });
});

describe('Case 7: pickAddButton', () => {
  it('Amazon id wins even if other buttons exist', () => {
    const amazonBtn = { id: 'add-to-cart-button', textContent: 'Add to Cart', visible: true };
    const genericBtn = { textContent: 'Add', visible: true };
    const result = pickAddButton([genericBtn, amazonBtn]);
    assert.equal(result, amazonBtn);
  });

  it('single generic Add wins', () => {
    const genericBtn = { textContent: 'Add to Cart', visible: true };
    const cancelBtn = { textContent: 'Cancel', visible: true };
    const result = pickAddButton([cancelBtn, genericBtn]);
    assert.equal(result, genericBtn);
  });

  it('two generic Add buttons results in null (ambiguous)', () => {
    const add1 = { textContent: 'Add', visible: true };
    const add2 = { textContent: 'Add', visible: true };
    assert.equal(pickAddButton([add1, add2]), null);
  });

  it('a Buy now button only results in null', () => {
    const buyNow = { textContent: 'Buy now', visible: true };
    assert.equal(pickAddButton([buyNow]), null);
  });

  it('never clicks buttons with checkout/pay/proceed text', () => {
    const checkoutBtn = { textContent: 'Proceed to Checkout', visible: true };
    const payBtn = { textContent: 'Pay Now', visible: true };
    assert.equal(pickAddButton([checkoutBtn, payBtn]), null);
  });

  it('returns null if no matches or candidates are invisible', () => {
    const hiddenAdd = { textContent: 'Add', visible: false };
    assert.equal(pickAddButton([hiddenAdd]), null);
    assert.equal(pickAddButton([]), null);
    assert.equal(pickAddButton(null), null);
  });
});

describe('Case 18: isMatchingProductPage (product-id match helper)', () => {
  it('returns true when both URLs have the same ASIN on Amazon', () => {
    const targetUrl = 'https://www.amazon.in/dp/B07T6X61N9?tag=dealscour-21';
    const landedUrl = 'https://www.amazon.in/gp/product/B07T6X61N9';
    assert.equal(isMatchingProductPage(targetUrl, landedUrl), true);
  });

  it('returns false when ASINs differ', () => {
    const targetUrl = 'https://www.amazon.in/dp/B07T6X61N9';
    const landedUrl = 'https://www.amazon.in/dp/B08XYZ1234';
    assert.equal(isMatchingProductPage(targetUrl, landedUrl), false);
  });

  it('returns false when landed page is a search page', () => {
    const targetUrl = 'https://www.amazon.in/dp/B07T6X61N9';
    const landedUrl = 'https://www.amazon.in/s?k=cashews';
    assert.equal(isMatchingProductPage(targetUrl, landedUrl), false);
  });

  it('returns false when hosts differ', () => {
    const targetUrl = 'https://www.amazon.in/dp/B07T6X61N9';
    const landedUrl = 'https://www.flipkart.com/dp/B07T6X61N9';
    assert.equal(isMatchingProductPage(targetUrl, landedUrl), false);
  });
});
