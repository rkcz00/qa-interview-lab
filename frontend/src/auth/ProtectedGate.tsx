import { useEffect, useState, useSyncExternalStore } from 'react'
import type { ReactNode } from 'react'
import { api } from '../api/index.ts'
import { SessionStore } from './session.ts'
import { ru } from './texts.ts'
import { Button } from '../ui/Button.tsx'
import { LoadingState } from '../ui/LoadingState.tsx'
import { Notice } from '../ui/Notice.tsx'

export function ProtectedGate({ children, requireLogin }: { children: ReactNode; requireLogin: () => void }) {
  const [session] = useState(() => new SessionStore(api.auth))
  const state = useSyncExternalStore(session.subscribe, session.getSnapshot)
  useEffect(() => { void session.restore(); return () => session.invalidate() }, [session])
  useEffect(() => { if (state.kind === 'anonymous') requireLogin() }, [state.kind, requireLogin])
  if (state.kind === 'authenticated') return children
  return <main className="auth-shell"><p className="eyebrow">{ru.brand}</p>
    {state.kind === 'error' ? <><h1>{ru.login}</h1><Notice>{ru.sessionError}</Notice>
      <Button variant="secondary" onClick={() => { void session.restore() }}>{ru.retry}</Button></> : <LoadingState message={ru.checking} />}
  </main>
}
