import type { ReactNode } from 'react'

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-2xl border border-slate-200 bg-white p-4 shadow-sm ${className}`}>{children}</section>
}

export function SectionTitle({ children }: { children: ReactNode }) {
  return <h2 className="text-sm font-bold uppercase tracking-wide text-slate-500">{children}</h2>
}

export function ErrorNote({ error }: { error: string | null }) {
  if (!error) return null
  return <p className="rounded-xl bg-rose-50 p-3 text-sm text-rose-700">{error}</p>
}

export const inputClass = 'w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-sm'
