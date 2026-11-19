import { useEffect, useState, useSyncExternalStore } from 'react'
import { api } from '../api/index.ts'
import type { Navigate } from '../auth/NavigationLink.tsx'
import type { Destination } from '../auth/routing.ts'
import { SessionStore } from '../auth/session.ts'
import { ru } from '../auth/texts.ts'
import { progressRu as text } from './texts.ts'
import { OverallProgress } from './OverallProgress.tsx'
import { AppShell } from '../ui/AppShell.tsx'
import { useOverview } from '../ui/OverviewContext.tsx'
import { usePageHeadingFocus } from '../ui/usePageHeadingFocus.ts'
import { Button } from '../ui/Button.tsx'
import { Notice } from '../ui/Notice.tsx'
import { LoadingState } from '../ui/LoadingState.tsx'
import { EmptyState } from '../ui/EmptyState.tsx'

function ProgressContent() {
  const { state, reload } = useOverview()
  const heading = usePageHeadingFocus(state.kind === 'ready' || state.kind === 'error')
  return <>
    <h1 tabIndex={-1} ref={heading}>{text.title}</h1>
    <p>{text.intro}</p>
    {state.kind === 'loading' && <LoadingState message={text.loading} />}
    {state.kind === 'error' && <><Notice>{state.message}</Notice><Button variant="secondary" onClick={reload}>{text.retry}</Button></>}
    {state.kind === 'ready' && <>
      <OverallProgress view={state.view} />
      {state.view.total === 0 && <EmptyState title={text.empty} />}
      <p>{text.rule}</p>
      <p className="help-text">{text.scope}</p>
    </>}
  </>
}

export default function ProgressApplication({ navigate, requireLogin }: { navigate: Navigate; requireLogin: (destination: Destination) => void }) {
  const [session] = useState(() => new SessionStore(api.auth))
  const authentication = useSyncExternalStore(session.subscribe, session.getSnapshot)
  useEffect(() => { void session.restore(); return () => session.invalidate() }, [session])
  useEffect(() => { if (authentication.kind === 'anonymous') requireLogin('/progress') }, [authentication.kind, requireLogin])
  return <AppShell className="progress-shell" navigate={navigate} canLogout={authentication.kind === 'authenticated'}>
    {authentication.kind === 'error' && <><Notice>{ru.sessionError}</Notice>
      <Button variant="secondary" onClick={() => { void session.restore() }}>{ru.retry}</Button></>}
    {authentication.kind === 'checking' && <LoadingState message={ru.checking} />}
    {authentication.kind === 'authenticated' && <ProgressContent />}
  </AppShell>
}
