import { PLATFORM_META, PLATFORMS, type Deal, type SavedNeed } from '../../lib/api'
import { formatINR } from '../../lib/money'
import { Card, SectionTitle } from '../../lib/ui'
import { buildMatrixRows } from './matrixRows'

const FRESHNESS_DOT: Record<Deal['freshness'], { label: string; className: string }> = {
  fresh: { label: 'Live', className: 'bg-emerald-100 text-emerald-800' },
  ok: { label: 'Recent', className: 'bg-sky-100 text-sky-800' },
  stale: { label: 'Stale', className: 'bg-amber-100 text-amber-800' },
  sample: { label: 'Sample', className: 'bg-slate-100 text-slate-600' },
}

export default function ComparisonMatrix({ needs, deals }: { needs: SavedNeed[]; deals: Deal[] }) {
  if (needs.length === 0) return null
  const rows = buildMatrixRows(needs, deals)

  return (
    <Card>
      <div className="flex items-center justify-between gap-2">
        <SectionTitle>Cross-Platform Price Matrix</SectionTitle>
        <span className="text-[11px] font-medium text-slate-500">Landed item price · unit rate</span>
      </div>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[30rem] border-collapse text-left text-xs">
          <thead>
            <tr className="border-b border-slate-200 text-[11px] text-slate-500">
              <th className="py-1.5 pr-2 font-semibold">Item</th>
              {PLATFORMS.map((p) => (
                <th key={p} className="px-1.5 py-1.5 font-semibold">
                  <span className="inline-flex items-center gap-1">
                    <span className="h-2 w-2 rounded-full" style={{ backgroundColor: PLATFORM_META[p].color }} />
                    {PLATFORM_META[p].name}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((row) => (
              <tr key={row.need.id}>
                <td className="py-2 pr-2 font-semibold text-slate-800">
                  <div className="flex items-center gap-1.5">
                    <span>{row.icon}</span>
                    <span className="truncate">{row.need.line_id}</span>
                    {row.need.qty > 1 && <span className="text-[11px] text-slate-500">×{row.need.qty}</span>}
                  </div>
                </td>
                {PLATFORMS.map((p) => {
                  const deal = row.byPlatform[p]
                  const isBest = row.bestPlatform === p
                  if (!deal) {
                    return (
                      <td key={p} className="px-1.5 py-2 text-slate-300">
                        —
                      </td>
                    )
                  }
                  return (
                    <td
                      key={p}
                      className={` rounded-lg px-1.5 py-1.5 align-top ${
                        isBest ? 'bg-emerald-50 font-bold text-emerald-900' : 'text-slate-700'
                      }`}
                    >
                      <div className="flex items-center gap-1">
                        <span>{formatINR(deal.unit_price_paise)}</span>
                        {isBest && <span className="rounded bg-emerald-600 px-1 py-0.2 text-[9px] font-extrabold uppercase text-white">Best</span>}
                      </div>
                      <div className="text-[10px] text-slate-500">
                        {formatINR(deal.unit_rate_paise)}/{deal.rate_basis_label}
                      </div>
                      <div className="mt-0.5 flex items-center gap-1">
                        <span className={`rounded px-1 py-0.2 text-[9px] font-bold ${FRESHNESS_DOT[deal.freshness].className}`}>
                          {FRESHNESS_DOT[deal.freshness].label}
                        </span>
                        {!deal.in_stock && <span className="text-[9px] font-bold text-rose-600">OOS</span>}
                      </div>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}
