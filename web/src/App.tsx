import { formatINR } from './lib/money'

export default function App() {
  return (
    <main className="mx-auto max-w-xl p-4 font-sans text-slate-900">
      <h1 className="text-2xl font-bold">DealScour</h1>
      <p className="mt-2 text-slate-600">
        Smallest set of baskets, most offer value. Example: two orders of {formatINR(50000)} earn{' '}
        {formatINR(10000)} cashback instead of {formatINR(5000)}.
      </p>
    </main>
  )
}
