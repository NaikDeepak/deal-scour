import { useEffect, useState } from 'react'
import SignIn from './features/auth/SignIn'
import BasketsPage from './features/baskets/BasketsPage'
import HouseholdPage from './features/household/HouseholdPage'
import OffersPage from './features/offers/OffersPage'
import PlansPage from './features/plans/PlansPage'
import PricesPage from './features/prices/PricesPage'
import { auth, setUnauthorizedHandler, type Me } from './lib/api'
import { usePreference } from './lib/preference'

type Tab = 'plan' | 'baskets' | 'offers' | 'prices' | 'household'
const TABS: { id: Tab; label: string }[] = [
  { id: 'plan', label: 'Plan' },
  { id: 'baskets', label: 'Baskets' },
  { id: 'offers', label: 'Offers' },
  { id: 'prices', label: 'Prices' },
  { id: 'household', label: 'Family' },
]

function inviteFromUrl(): string | null {
  return new URLSearchParams(window.location.search).get('invite')
}

export default function App() {
  const [tab, setTab] = usePreference<Tab>('tab', 'plan')
  const [me, setMe] = useState<Me | null | 'loading'>('loading')
  const [invite] = useState(inviteFromUrl)

  useEffect(() => {
    setUnauthorizedHandler(() => setMe(null))
    auth.me().then(setMe).catch(() => setMe(null))
  }, [])

  function signedIn(m: Me) {
    if (invite) window.history.replaceState(null, '', '/')
    setMe(m)
  }

  return (
    <main className="mx-auto min-h-screen max-w-xl bg-slate-50 px-4 pb-10 pt-5 font-sans text-slate-900">
      <header className="mb-4">
        <h1 className="text-2xl font-black">DealScour</h1>
        <p className="text-sm text-slate-600">The fewest baskets that earn the most offer value.</p>
      </header>
      {me === 'loading' ? null : me === null ? (
        <SignIn inviteCode={invite} onSignedIn={signedIn} />
      ) : (
        <>
          <nav className="sticky top-0 z-10 mb-4 flex gap-1 rounded-xl bg-slate-200/80 p-1 backdrop-blur" aria-label="Sections">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                aria-current={tab === t.id ? 'page' : undefined}
                onClick={() => setTab(t.id)}
                className={`flex-1 rounded-lg py-1.5 text-xs font-bold sm:text-sm ${tab === t.id ? 'bg-white shadow-sm' : 'text-slate-600'}`}
              >
                {t.label}
              </button>
            ))}
          </nav>
          {tab === 'plan' && <PlansPage onAccepted={() => setTab('baskets')} />}
          {tab === 'baskets' && <BasketsPage />}
          {tab === 'offers' && <OffersPage />}
          {tab === 'prices' && <PricesPage />}
          {tab === 'household' && <HouseholdPage me={me} onSignedOut={() => setMe(null)} />}
        </>
      )}
    </main>
  )
}
