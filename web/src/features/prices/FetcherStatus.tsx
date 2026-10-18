import { useCallback, useEffect, useState } from 'react'
import { catalog, PLATFORM_META, type SourceStatus } from '../../lib/api'
import { Card, SectionTitle } from '../../lib/ui'

export default function FetcherStatus({ onRefreshed }: { onRefreshed: () => void }) {
  const [status, setStatus] = useState<{ platforms: SourceStatus[]; quick_commerce: string } | null>(null)
  const [note, setNote] = useState<string | null>(null)

  const load = useCallback(() => {
    catalog.sourceStatus().then(setStatus).catch(() => setStatus(null))
  }, [])
  useEffect(load, [load])

  async function refresh() {
    try {
      const { queued } = await catalog.refreshPrices()
      setNote(queued === 0 ? 'Everything is up to date.' : `Checking ${queued} product${queued === 1 ? '' : 's'}: about ${Math.ceil(queued * 12 / 60)} min. Prices update as they come in.`)
      setTimeout(() => {
        load()
        onRefreshed()
      }, 15000)
    } catch (e) {
      setNote((e as Error).message.replace(/^\d+: /, ''))
    }
  }

  if (!status) return null
  return (
    <Card className="space-y-2">
      <SectionTitle>Automatic prices</SectionTitle>
      <ul className="space-y-1 text-xs">
        {status.platforms.map((p) => (
          <li key={p.platform} className="flex justify-between gap-2">
            <span className="font-semibold">{PLATFORM_META[p.platform].name}</span>
            <span className="text-slate-600">
              {!p.enabled_by_config
                ? 'Off (set DEALSCOUR_FETCHERS=1)'
                : p.disabled_until && new Date(p.disabled_until) > new Date()
                  ? `Paused until ${new Date(p.disabled_until).toLocaleString('en-IN')} (site blocked us)`
                  : p.last_success_at
                    ? `Last checked ${new Date(p.last_success_at).toLocaleString('en-IN')}`
                    : 'Not checked yet'}
            </span>
          </li>
        ))}
        <li className="flex justify-between gap-2 text-slate-500">
          <span>Blinkit, Zepto, Instamart</span>
          <span>Manual only (the sites block automated checks)</span>
        </li>
      </ul>
      <button type="button" onClick={refresh} className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-bold">
        Refresh prices now
      </button>
      {note && <p className="text-xs text-slate-600">{note}</p>}
    </Card>
  )
}
