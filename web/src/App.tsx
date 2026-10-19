import { useEffect, useState } from 'react'
import SignIn from './features/auth/SignIn'
import BasketsPage from './features/baskets/BasketsPage'
import DealsPage from './features/deals/DealsPage'
import HouseholdPage from './features/household/HouseholdPage'
import OffersPage from './features/offers/OffersPage'
import PlansPage from './features/plans/PlansPage'
import PricesPage from './features/prices/PricesPage'
import RadarPage from './features/radar/RadarPage'
import { auth, setUnauthorizedHandler, type Me } from './lib/api'
import { EXPECTED_EXTENSION_VERSION, isExtensionVersionOlder } from './lib/extension'
import { usePreference } from './lib/preference'

export type ExtensionState =
  | { kind: 'checking' }
  | { kind: 'loaded'; version: string }
  | { kind: 'not_found' }

export function ExtensionBadge({
  state,
  expectedVersion = EXPECTED_EXTENSION_VERSION,
}: {
  state: ExtensionState
  expectedVersion?: string
}) {
  if (state.kind === 'checking') {
    return null
  }
  if (state.kind === 'not_found') {
    return (
      <span className="inline-block rounded-full bg-slate-200 px-2.5 py-0.5 text-[11px] font-semibold text-slate-600">
        Extension not found
      </span>
    )
  }
  if (isExtensionVersionOlder(state.version, expectedVersion)) {
    return (
      <span className="inline-block rounded-full bg-amber-100 px-2.5 py-0.5 text-[11px] font-semibold text-amber-800">
        Reload the extension: {state.version} loaded, {expectedVersion} available (chrome://extensions)
      </span>
    )
  }
  return (
    <span className="inline-block rounded-full bg-emerald-100 px-2.5 py-0.5 text-[11px] font-semibold text-emerald-800">
      Extension {state.version} ✓
    </span>
  )
}

type Tab = 'deals' | 'radar' | 'plan' | 'baskets' | 'offers' | 'prices' | 'household'
const TABS: { id: Tab; label: string }[] = [
  { id: 'deals', label: 'Deals' },
  { id: 'radar', label: 'Radar' },
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
  const [extState, setExtState] = useState<ExtensionState>({ kind: 'checking' })

  useEffect(() => {
    setUnauthorizedHandler(() => setMe(null))
    auth.me().then(setMe).catch(() => setMe(null))
  }, [])

  useEffect(() => {
    let answered = false
    function onMessage(e: MessageEvent) {
      if (e.source !== window || !e.data || typeof e.data.type !== 'string') return
      if (e.data.type === 'DEALSCOUR_EXTENSION_READY' && typeof e.data.version === 'string') {
        answered = true
        setExtState({ kind: 'loaded', version: e.data.version })
      }
    }
    window.addEventListener('message', onMessage)
    window.postMessage({ type: 'DEALSCOUR_PING_EXTENSION' }, window.location.origin)
    const timer = window.setTimeout(() => {
      if (!answered) {
        setExtState({ kind: 'not_found' })
      }
    }, 1000)
    return () => {
      window.removeEventListener('message', onMessage)
      window.clearTimeout(timer)
    }
  }, [])

  function signedIn(m: Me) {
    if (invite) window.history.replaceState(null, '', '/')
    setMe(m)
  }

  return (
    <main className="mx-auto min-h-screen max-w-xl bg-slate-50 px-4 pb-10 pt-5 font-sans text-slate-900">
      <header className="mb-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h1 className="text-2xl font-black">DealScour</h1>
          <ExtensionBadge state={extState} />
        </div>
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
          {tab === 'deals' && <DealsPage />}
          {tab === 'radar' && <RadarPage />}
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
