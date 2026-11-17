import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import type { ReactNode } from 'react'
import { api } from '../api/index.ts'
import { NavigationLink } from '../auth/NavigationLink.tsx'
import type { Navigate } from '../auth/NavigationLink.tsx'
import { ru } from '../auth/texts.ts'
import { learnerNavigation } from './navigation.ts'
import { LogoutStore } from './logout.ts'
import { Button } from './Button.tsx'
import { Notice } from './Notice.tsx'
import { LoadingState } from './LoadingState.tsx'

interface Props {
  navigate: Navigate
  canLogout: boolean
  className?: string
  children: ReactNode
}

export function AppShell({ navigate, canLogout, className = '', children }: Props) {
  const [logout] = useState(() => new LogoutStore(api.auth))
  const state = useSyncExternalStore(logout.subscribe, logout.getSnapshot)
  const errorBox = useRef<HTMLDivElement>(null)
  useEffect(() => () => logout.invalidate(), [logout])
  useEffect(() => { if (state.kind === 'signed_out') navigate('/login', true) }, [state.kind, navigate])
  useEffect(() => { if (state.kind === 'error') errorBox.current?.focus() }, [state.kind])
  return <main className={`learning-shell ${className}`.trim()}>
    <nav className="learning-nav app-nav" aria-label="Основная навигация">
      <NavigationLink to="/" navigate={navigate}>{ru.home}</NavigationLink>
      {learnerNavigation(window.location.pathname).map(item =>
        <NavigationLink key={item.to} to={item.to} navigate={navigate} current={item.current}>{item.label}</NavigationLink>)}
      {canLogout && <Button variant="secondary" busy={state.kind === 'pending'} onClick={() => { void logout.logout() }}>
        {state.kind === 'pending' ? ru.signingOut : ru.logout}
      </Button>}
    </nav>
    {state.kind === 'pending' && <LoadingState message={ru.signingOut} />}
    {state.kind === 'error' && <Notice tabIndex={-1} ref={errorBox}>{state.message}</Notice>}
    {children}
  </main>
}
