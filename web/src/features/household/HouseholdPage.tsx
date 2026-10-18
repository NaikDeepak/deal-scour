import { useCallback, useEffect, useState } from 'react'
import { auth, type Me, type Member } from '../../lib/api'
import { Card, ErrorNote, SectionTitle } from '../../lib/ui'

export default function HouseholdPage({ me, onSignedOut }: { me: Me; onSignedOut: () => void }) {
  const [members, setMembers] = useState<Member[]>([])
  const [invite, setInvite] = useState<{ link: string; expires: string } | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    auth.members().then(setMembers).catch((e: Error) => setError(e.message))
  }, [])
  useEffect(load, [load])

  async function invite() {
    try {
      const { invite_code, expires_at } = await auth.invite()
      setInvite({
        link: `${window.location.origin}/?invite=${encodeURIComponent(invite_code)}`,
        expires: new Date(expires_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }),
      })
    } catch (e) {
      setError((e as Error).message)
    }
  }

  async function remove(m: Member) {
    try {
      await auth.removeMember(m.user_id)
      load()
    } catch (e) {
      setError((e as Error).message)
    }
  }

  async function signOut() {
    try {
      await auth.logout()
    } finally {
      onSignedOut()
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <SectionTitle>Household</SectionTitle>
        <ul className="mt-2 divide-y divide-slate-100 text-sm">
          {members.map((m) => (
            <li key={m.user_id} className="flex items-center justify-between gap-2 py-2">
              <span className="min-w-0 truncate">
                <strong>{m.name ?? m.email}</strong> <span className="text-xs text-slate-500">{m.name ? m.email : ''}</span>
              </span>
              <span className="flex shrink-0 items-center gap-2 text-xs">
                <span className="rounded bg-slate-100 px-1.5 py-0.5 font-bold uppercase">{m.role}</span>
                {me.role === 'owner' && m.user_id !== me.user.id && (
                  <button type="button" onClick={() => remove(m)} className="font-semibold text-rose-600">
                    Remove
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>
        {me.role === 'owner' && (
          <>
            <button type="button" onClick={invite} className="mt-3 rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-bold text-white">
              Create invite link
            </button>
            {invite && (
              <div className="mt-2 space-y-1 rounded-lg bg-amber-50 p-2 text-xs">
                <p>Send this link to one family member. It works once, until {invite.expires}, and is shown only now:</p>
                <code className="block select-all break-all rounded bg-white p-1.5">{invite.link}</code>
                {'clipboard' in navigator && (
                  <button type="button" onClick={() => void navigator.clipboard.writeText(invite.link)} className="font-semibold text-orange-700">
                    Copy link
                  </button>
                )}
              </div>
            )}
          </>
        )}
      </Card>
      <ErrorNote error={error} />
      <button type="button" onClick={signOut} className="w-full rounded-xl border border-slate-300 py-2 text-sm font-bold">
        Sign out ({me.user.email})
      </button>
    </div>
  )
}
