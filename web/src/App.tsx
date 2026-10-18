import PlansPage from './features/plans/PlansPage'

export default function App() {
  return (
    <main className="mx-auto min-h-screen max-w-xl bg-slate-50 px-4 py-5 font-sans text-slate-900">
      <header className="mb-4">
        <h1 className="text-2xl font-black">DealScour</h1>
        <p className="text-sm text-slate-600">The fewest baskets that earn the most offer value.</p>
      </header>
      <PlansPage />
    </main>
  )
}
