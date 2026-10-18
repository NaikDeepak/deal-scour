import { useState } from 'react'
import { auth, type Me } from '../../lib/api'
import { Card, ErrorNote, inputClass } from '../../lib/ui'

export default function SignIn({ inviteCode, onSignedIn }: { inviteCode: string | null; onSignedIn: (me: Me) => void }) {
  const [step, setStep] = useState<'email' | 'code'>('email')
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function send() {
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) {
      setError('Enter a valid email address.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await auth.requestCode(email.trim().toLowerCase(), inviteCode)
      setStep('code')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function verify() {
    setBusy(true)
    setError(null)
    try {
      onSignedIn(await auth.verify(email.trim().toLowerCase(), code.trim(), inviteCode, name.trim() || null))
    } catch {
      setError('That code is wrong or expired. Check the latest email, or request a new code.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="space-y-3">
      <h2 className="text-lg font-black">{inviteCode ? 'Join your family on DealScour' : 'Sign in'}</h2>
      {step === 'email' ? (
        <>
          <p className="text-sm text-slate-600">We'll email you a 6-digit code. No password needed.</p>
          <input className={inputClass} type="email" autoComplete="email" placeholder="you@example.com" value={email} onChange={(e) => setEmail(e.target.value)} />
          {inviteCode && (
            <input className={inputClass} autoComplete="name" placeholder="Your name (shown to your family)" value={name} onChange={(e) => setName(e.target.value)} />
          )}
          <button type="button" disabled={busy} onClick={send} className="w-full rounded-xl bg-orange-600 py-2.5 text-sm font-bold text-white disabled:opacity-40">
            Email me a code
          </button>
          <p className="text-xs text-slate-500">Only the owner and invited family members can sign in.</p>
        </>
      ) : (
        <>
          <p className="text-sm text-slate-600">
            If <strong>{email}</strong> can sign in, a code is on its way. It's valid for 10 minutes.
          </p>
          <input
            className={`${inputClass} text-center text-lg tracking-[0.4em]`}
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            placeholder="••••••"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
          />
          <button
            type="button"
            disabled={busy || code.length !== 6}
            onClick={verify}
            className="w-full rounded-xl bg-orange-600 py-2.5 text-sm font-bold text-white disabled:opacity-40"
          >
            Sign in
          </button>
          <button type="button" onClick={() => setStep('email')} className="w-full text-xs font-semibold text-slate-500">
            Use a different email
          </button>
        </>
      )}
      <ErrorNote error={error} />
    </Card>
  )
}
