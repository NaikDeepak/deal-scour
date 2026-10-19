import manifest from '../../../extension/manifest.json'

export const EXPECTED_EXTENSION_VERSION: string = manifest.version

export function isExtensionVersionOlder(loaded: string, expected: string = EXPECTED_EXTENSION_VERSION): boolean {
  const parse = (v: string) =>
    v
      .trim()
      .replace(/^v/i, '')
      .split('.')
      .map((part) => Number.parseInt(part, 10) || 0)

  const a = parse(loaded)
  const b = parse(expected)
  const len = Math.max(a.length, b.length)
  for (let i = 0; i < len; i += 1) {
    const av = a[i] ?? 0
    const bv = b[i] ?? 0
    if (av < bv) return true
    if (av > bv) return false
  }
  return false
}
