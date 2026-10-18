import BasketsPage from './features/baskets/BasketsPage'
import OffersPage from './features/offers/OffersPage'
import PlansPage from './features/plans/PlansPage'
import PricesPage from './features/prices/PricesPage'
import { usePreference } from './lib/preference'

type Tab = 'plan' | 'baskets' | 'offers' | 'prices'
const TABS: { id: Tab; label: string }[] = [
  { id: 'plan', label: 'Plan' },
  { id: 'baskets', label: 'Baskets' },
  { id: 'offers', label: 'Offers' },
  { id: 'prices', label: 'Prices' },
]

export default function App() {
  const [tab, setTab] = usePreference<Tab>('tab', 'plan')
  return (
    <main className="mx-auto min-h-screen max-w-xl bg-slate-50 px-4 pb-10 pt-5 font-sans text-slate-900">
      <header className="mb-4">
        <h1 className="text-2xl font-black">DealScour</h1>
        <p className="text-sm text-slate-600">The fewest baskets that earn the most offer value.</p>
      </header>
      <nav className="sticky top-0 z-10 mb-4 flex gap-1 rounded-xl bg-slate-200/80 p-1 backdrop-blur" aria-label="Sections">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            aria-current={tab === t.id ? 'page' : undefined}
            onClick={() => setTab(t.id)}
            className={`flex-1 rounded-lg py-1.5 text-sm font-bold ${tab === t.id ? 'bg-white shadow-sm' : 'text-slate-600'}`}
          >
            {t.label}
          </button>
        ))}
      </nav>
      {tab === 'plan' && <PlansPage onAccepted={() => setTab('baskets')} />}
      {tab === 'baskets' && <BasketsPage />}
      {tab === 'offers' && <OffersPage />}
      {tab === 'prices' && <PricesPage />}
    </main>
  )
}
