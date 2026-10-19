// Injected into shop search tabs (read-only) to collect up to 5 product candidates.
// Never clicks, types, or modifies the page (ADR-020).

const _lib =
  typeof module !== 'undefined' && module.exports
    ? require('./lib.js')
    : {
        parseRupeesToPaise: typeof parseRupeesToPaise === 'function' ? parseRupeesToPaise : () => null,
        isProductPageUrl: typeof isProductPageUrl === 'function' ? isProductPageUrl : () => false,
        extractProductId: typeof extractProductId === 'function' ? extractProductId : () => null,
        parsePackLabel: typeof parsePackLabel === 'function' ? parsePackLabel : () => null,
      };

function parseAttributes(attrStr) {
  const attrs = {};
  const re = /([a-zA-Z0-9_-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/g;
  let m;
  while ((m = re.exec(attrStr)) !== null) {
    attrs[m[1].toLowerCase()] = m[2] ?? m[3] ?? m[4] ?? '';
  }
  return attrs;
}

function stripTags(html) {
  return html
    .replace(/<!--[\s\S]*?-->/g, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

// Lightweight HTML-to-DOM parser for Node tests and search snippet fixtures (no external deps).
function parseHtmlToDom(html, baseUrl = 'https://www.amazon.in') {
  const cleanHtml = String(html || '').replace(/<!--[\s\S]*?-->/g, '');
  const root = {
    tagName: 'DIV',
    attributes: {},
    children: [],
    parentElement: null,
    baseURI: baseUrl,
    get textContent() {
      return this.children.map((c) => c.textContent).join(' ').replace(/\s+/g, ' ').trim();
    },
    getAttribute(name) {
      return this.attributes[String(name).toLowerCase()] ?? null;
    },
    querySelectorAll(selector) {
      const results = [];
      const walk = (node) => {
        for (const child of node.children || []) {
          if ( child.tagName ) {
            if (selector === 'a[href]' && child.tagName === 'A' && child.getAttribute('href')) {
              results.push(child);
            } else if (selector === 'img[alt]' && child.tagName === 'IMG' && child.getAttribute('alt')) {
              results.push(child);
            }
            walk(child);
          }
        }
      };
      walk(this);
      return results;
    },
  };

  const stack = [root];
  const tokenRe = /<(\/?)([a-zA-Z0-9]+)([^>]*?)(\/?)>|([^<]+)/g;
  const voidTags = new Set(['img', 'br', 'hr', 'input', 'meta', 'link']);
  let match;

  while ((match = tokenRe.exec(cleanHtml)) !== null) {
    const [, closing, rawTag, attrStr, selfClosing, textNode] = match;
    const current = stack[stack.length - 1];
    if (textNode !== undefined) {
      const t = textNode.replace(/\s+/g, ' ');
      if (t.trim()) {
        current.children.push({
          tagName: null,
          textContent: t,
          children: [],
          parentElement: current,
        });
      }
      continue;
    }

    const tag = rawTag.toUpperCase();
    if (closing) {
      for (let i = stack.length - 1; i > 0; i -= 1) {
        if (stack[i].tagName === tag) {
          stack.length = i;
          break;
        }
      }
      continue;
    }

    const attrs = parseAttributes(attrStr || '');
    const el = {
      tagName: tag,
      attributes: attrs,
      children: [],
      parentElement: current,
      baseURI: baseUrl,
      get textContent() {
        return this.children.map((c) => c.textContent).join(' ').replace(/\s+/g, ' ').trim();
      },
      getAttribute(name) {
        return this.attributes[String(name).toLowerCase()] ?? null;
      },
      querySelectorAll: root.querySelectorAll,
    };
    if (tag === 'A' && attrs.href) {
      try {
        el.href = new URL(attrs.href, baseUrl).href;
      } catch {
        el.href = attrs.href;
      }
    }
    current.children.push(el);

    if (!selfClosing && !voidTags.has(rawTag.toLowerCase())) {
      stack.push(el);
    }
  }

  return root;
}

function isSponsoredElement(el) {
  if (!el || typeof el.getAttribute !== 'function') return false;
  const compType = (el.getAttribute('data-component-type') || '').toLowerCase();
  if (compType.includes('sponsored')) return true;
  if (el.getAttribute('data-ad') === 'true') return true;
  const cls = (el.getAttribute('class') || '').toLowerCase();
  if (cls.includes('adholder') || cls.includes('sponsored')) return true;
  return false;
}

function findCardForAnchor(anchor) {
  let curr = anchor.parentElement;
  let fallback = curr || anchor;
  while (curr && curr.parentElement) {
    if (isSponsoredElement(curr)) {
      return { card: curr, sponsored: true };
    }
    const cls = (curr.getAttribute && curr.getAttribute('class')) || '';
    const hasCardMarker =
      (curr.getAttribute &&
        (curr.getAttribute('data-asin') ||
          curr.getAttribute('data-id') ||
          curr.getAttribute('data-component-type') === 's-search-result')) ||
      /\b(s-result-item|product-card|card|search-card)\b/i.test(cls);

    if (hasCardMarker) {
      const text = curr.textContent || '';
      const hasSponsoredBadge = /^\s*sponsored\b/i.test(text);
      return { card: curr, sponsored: hasSponsoredBadge || isSponsoredElement(curr) };
    }
    curr = curr.parentElement;
  }
  return { card: fallback, sponsored: isSponsoredElement(fallback) };
}

function extractPriceFromCard(cardText) {
  if (!cardText) return null;
  const m = cardText.match(/₹\s*([\d,]+(?:\.\d{1,2})?)/);
  if (m) {
    return _lib.parseRupeesToPaise(m[1]);
  }
  return null;
}

function extractCandidates(rootInput) {
  let root = rootInput;
  if (typeof root === 'string') {
    root = parseHtmlToDom(root);
  } else if (!root && typeof document !== 'undefined') {
    root = document;
  }
  if (!root || typeof root.querySelectorAll !== 'function') {
    return [];
  }

  const baseUrl =
    root.baseURI ||
    (typeof window !== 'undefined' && window.location ? window.location.href : 'https://www.amazon.in');
  const anchors = Array.from(root.querySelectorAll('a[href]'));

  // Group anchors by productId so if the first anchor is an image link, we can still read the text anchor
  const byProductId = new Map();

  for (const a of anchors) {
    const rawHref = a.href || (typeof a.getAttribute === 'function' ? a.getAttribute('href') : '');
    if (!rawHref) continue;
    let resolvedUrl;
    try {
      resolvedUrl = new URL(rawHref, baseUrl).href;
    } catch {
      continue;
    }

    if (!_lib.isProductPageUrl(resolvedUrl)) {
      continue;
    }

    const { card, sponsored } = findCardForAnchor(a);
    if (sponsored) {
      continue;
    }

    const productId = _lib.extractProductId(resolvedUrl);
    if (!productId) {
      continue;
    }

    const anchorText = (a.textContent || '').replace(/\s+/g, ' ').trim();
    const existing = byProductId.get(productId);
    if (!existing) {
      byProductId.set(productId, {
        url: resolvedUrl,
        card,
        texts: anchorText ? [anchorText] : [],
      });
    } else if (anchorText && !existing.texts.includes(anchorText)) {
      existing.texts.push(anchorText);
    }
  }

  const candidates = [];
  for (const [, entry] of byProductId.entries()) {
    if (candidates.length >= 5) break;
    const cardText = (entry.card && entry.card.textContent ? entry.card.textContent : '')
      .replace(/\s+/g, ' ')
      .trim();

    // Pick best descriptive title from anchors in this card
    const meaningfulTexts = entry.texts.filter(
      (t) => t.length > 3 && !/^(view details|buy now|add)$/i.test(t)
    );
    let title = meaningfulTexts[0] || entry.texts[0] || '';
    if (!title && entry.card && typeof entry.card.querySelectorAll === 'function') {
      const imgs = entry.card.querySelectorAll('img[alt]');
      if (imgs.length > 0) {
        title = (imgs[0].getAttribute('alt') || '').trim();
      }
    }
    if (!title) continue;

    const price_paise = extractPriceFromCard(cardText);
    const pack_label = _lib.parsePackLabel(title) || _lib.parsePackLabel(cardText);

    candidates.push({
      url: entry.url,
      title,
      price_paise,
      pack_label,
    });
  }

  return candidates;
}

function hasProductLinks(rootInput) {
  let root = rootInput;
  if (typeof root === 'string') {
    root = parseHtmlToDom(root);
  } else if (!root && typeof document !== 'undefined') {
    root = document;
  }
  if (!root || typeof root.querySelectorAll !== 'function') {
    return false;
  }

  const baseUrl =
    root.baseURI ||
    (typeof window !== 'undefined' && window.location ? window.location.href : 'https://www.amazon.in');
  const anchors = Array.from(root.querySelectorAll('a[href]'));

  for (const a of anchors) {
    const rawHref = a.href || (typeof a.getAttribute === 'function' ? a.getAttribute('href') : '');
    if (!rawHref) continue;
    let resolvedUrl;
    try {
      resolvedUrl = new URL(rawHref, baseUrl).href;
    } catch {
      continue;
    }
    if (_lib.isProductPageUrl(resolvedUrl)) {
      return true;
    }
  }
  return false;
}

async function waitForCandidates(rootInput, { timeoutMs = 8000, pollIntervalMs = 500 } = {}) {
  const getRoot = () => {
    if (typeof rootInput === 'function') return rootInput();
    if (typeof rootInput === 'string') return parseHtmlToDom(rootInput);
    if (rootInput) return rootInput;
    if (typeof document !== 'undefined') return document;
    return null;
  };

  const startTime = Date.now();
  while (true) {
    const root = getRoot();
    if (root && hasProductLinks(root)) {
      const candidates = extractCandidates(root);
      if (candidates.length > 0) {
        return { status: 'found', candidates };
      }
    }
    const elapsed = Date.now() - startTime;
    if (elapsed + pollIntervalMs > timeoutMs) {
      break;
    }
    await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
  }

  const finalRoot = getRoot();
  if (finalRoot && hasProductLinks(finalRoot)) {
    const candidates = extractCandidates(finalRoot);
    if (candidates.length > 0) {
      return { status: 'found', candidates };
    }
  }

  return { status: 'no_links', candidates: [] };
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    extractCandidates,
    hasProductLinks,
    waitForCandidates,
    parseHtmlToDom,
    stripTags,
    parsePackLabel: _lib.parsePackLabel,
  };
}
