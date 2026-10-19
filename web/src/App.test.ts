import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { ExtensionBadge } from './App'
import { EXPECTED_EXTENSION_VERSION } from './lib/extension'

describe('Case 18: Extension version badge in App header', () => {
  it('exports EXPECTED_EXTENSION_VERSION 0.3.0 from extension/manifest.json', () => {
    expect(EXPECTED_EXTENSION_VERSION).toBe('0.3.0')
  })

  it('renders green matching badge when extension version matches EXPECTED_EXTENSION_VERSION', () => {
    const html = renderToStaticMarkup(
      createElement(ExtensionBadge, {
        state: { kind: 'loaded', version: '0.3.0' },
      }),
    )
    expect(html).toContain('Extension 0.3.0 ✓')
    expect(html).toContain('bg-emerald-100')
    expect(html).toContain('text-emerald-800')
  })

  it('renders amber reload badge with chrome://extensions when loaded version is older', () => {
    const html = renderToStaticMarkup(
      createElement(ExtensionBadge, {
        state: { kind: 'loaded', version: '0.2.0' },
      }),
    )
    expect(html).toContain('Reload the extension: 0.2.0 loaded, 0.3.0 available')
    expect(html).toContain('chrome://extensions')
    expect(html).toContain('bg-amber-100')
    expect(html).toContain('text-amber-800')
  })

  it('renders grey Extension not found badge when there is no answer to the ping within 1 s', () => {
    const html = renderToStaticMarkup(
      createElement(ExtensionBadge, {
        state: { kind: 'not_found' },
      }),
    )
    expect(html).toContain('Extension not found')
    expect(html).toContain('bg-slate-200')
    expect(html).toContain('text-slate-600')
  })
})
