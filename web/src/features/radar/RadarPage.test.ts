import { describe, expect, it } from 'vitest'
import { formatVerdictBadge, parseChannelInput } from './RadarPage'

describe('RadarPage helpers', () => {
  it('extracts normalized peer_id from Telegram Web URLs or raw ids', () => {
    expect(parseChannelInput('https://web.telegram.org/k/#-1001191090845')).toBe('-1001191090845')
    expect(parseChannelInput('https://web.telegram.org/a/#-1001191090845')).toBe('-1001191090845')
    expect(parseChannelInput('#-1001191090845')).toBe('-1001191090845')
    expect(parseChannelInput(' -1001191090845 ')).toBe('-1001191090845')
  })

  it('formats verdict badges with clear labels and styles', () => {
    expect(formatVerdictBadge('good').label).toBe('GOOD')
    expect(formatVerdictBadge('expired').label).toBe('Expired')
    expect(formatVerdictBadge('not_relevant').label).toBe('Not relevant')
    expect(formatVerdictBadge('unsupported_link').label).toBe('Unsupported link')
  })
})
