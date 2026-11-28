import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import type { ReactNode } from 'react'
import { api } from '../api/index.ts'
import { NavigationLink } from '../auth/NavigationLink.tsx'
import type { Navigate } from '../auth/NavigationLink.tsx'
import { ru } from '../auth/texts.ts'
import { ProgressStore } from '../progress/model.ts'
import { learnerNavigation } from './navigation.ts'
import { LogoutStore } from './logout.ts'
import { Button } from './Button.tsx'
import { Notice } from './Notice.tsx'
import { LoadingState } from './LoadingState.tsx'
import { OverviewContext } from './OverviewContext.tsx'
import { TopicSidebar } from './TopicSidebar.tsx'
import type { Language } from '../api/types.ts'

interface Props {
  navigate: Navigate
  canLogout: boolean
  className?: string
  topicId?: string | null
  materialLanguage?: Language
  children: ReactNode
  beforeLogout?: () => boolean
}

export function AppShell({ navigate, canLogout, className = '', topicId, materialLanguage, children, beforeLogout }: Props) {
  const [logout] = useState(() => new LogoutStore(api.auth))
  const state = useSyncExternalStore(logout.subscribe, logout.getSnapshot)
  const [overview] = useState(() => new ProgressStore(api))
  const summary = useSyncExternalStore(overview.subscribe, overview.getSnapshot)
  const reload = useCallback(() => { void overview.load() }, [overview])
  const errorBox = useRef<HTMLDivElement>(null)
  useEffect(() => () => logout.invalidate(), [logout])
  useEffect(() => { if (state.kind === 'signed_out') navigate('/login', true) }, [state.kind, navigate])
  useEffect(() => { if (state.kind === 'error') errorBox.current?.focus() }, [state.kind])
  useEffect(() => {
    if (!canLogout) return
    reload()
    const refresh = () => { void overview.load(true) }
    const preserveReset = (event: Event) => {
      if (window.location.pathname === '/progress' && overview.ownsReset()) event.preventDefault()
    }
    window.addEventListener('qil-progress-changed', refresh)
    window.addEventListener('qil-progress-invalidated', preserveReset)
    return () => {
      overview.invalidate()
      window.removeEventListener('qil-progress-changed', refresh)
      window.removeEventListener('qil-progress-invalidated', preserveReset)
    }
  }, [canLogout, overview, reload])
  useEffect(() => { if (summary.kind === 'authentication') navigate('/login', true) }, [summary.kind, navigate])
  return <OverviewContext value={{ state: summary, reload, store: overview }}>
    <div className="app-shell">
      <header className="app-header">
        <NavigationLink to="/" navigate={navigate} className="app-brand">{ru.brand}</NavigationLink>
        <nav className="app-nav" aria-label="Основная навигация">
          {learnerNavigation(window.location.pathname).map(item =>
            <NavigationLink key={item.to} to={item.to} navigate={navigate} current={item.current}>{item.label}</NavigationLink>)}
          {canLogout && <Button variant="secondary" busy={state.kind === 'pending'} onClick={() => { if (!beforeLogout || beforeLogout()) void logout.logout() }}>
            {state.kind === 'pending' ? ru.signingOut : ru.logout}
          </Button>}
        </nav>
      </header>
      <div className={canLogout ? 'app-layout' : 'app-layout is-checking'}>
        {canLogout && <TopicSidebar navigate={navigate} topicId={topicId} materialLanguage={materialLanguage} />}
        <main className={`app-content learning-shell ${className}`.trim()}>
          {state.kind === 'pending' && <LoadingState message={ru.signingOut} />}
          {state.kind === 'error' && <Notice tabIndex={-1} ref={errorBox}>{state.message}</Notice>}
          {children}
        </main>
      </div>
    </div>
  </OverviewContext>
}
