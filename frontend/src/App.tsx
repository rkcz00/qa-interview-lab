import { lazy, Suspense, useCallback, useEffect, useState } from 'react'
import { NavigationLink } from './auth/NavigationLink.tsx'
import { resolveRoute } from './auth/routing.ts'
import type { Route } from './auth/routing.ts'
import { ru } from './auth/texts.ts'

const AuthApplication = lazy(() => import('./auth/AuthApplication.tsx'))

export default function App() {
  const [pathname, setPathname] = useState(window.location.pathname)
  const [registeredEmail, setRegisteredEmail] = useState<string>()
  const route = resolveRoute(pathname)
  const move = useCallback((target: Route, replace = false) => {
    if (replace) window.history.replaceState(null, '', target)
    else window.history.pushState(null, '', target)
    setPathname(target)
  }, [])
  const navigate = useCallback((target: Route, replace = false) => {
    setRegisteredEmail(undefined)
    move(target, replace)
  }, [move])
  const onRegistered = useCallback((email: string) => {
    setRegisteredEmail(email)
    move('/login', true)
  }, [move])

  useEffect(() => {
    const changed = () => { setPathname(window.location.pathname); setRegisteredEmail(undefined) }
    window.addEventListener('popstate', changed)
    return () => window.removeEventListener('popstate', changed)
  }, [])
  useEffect(() => {
    document.title = route === '/' ? ru.brand : `${route === '/register' ? ru.register : route === '/login' ? ru.login : route === '/session' ? ru.session : ru.notFound} — ${ru.brand}`
  }, [route])

  if (route && route !== '/') return <Suspense fallback={<main><p role="status">{ru.checking}</p></main>}>
    <AuthApplication key={route} route={route} navigate={navigate} registeredEmail={registeredEmail} onRegistered={onRegistered} />
  </Suspense>
  if (!route) return <main><h1>{ru.notFound}</h1><NavigationLink to="/" navigate={navigate}>{ru.home}</NavigationLink></main>
  return (
    <main>
      <p className="eyebrow">{ru.audience}</p>
      <h1>{ru.brand}</h1>
      <p>{ru.intro}</p>
      <nav className="home-actions" aria-label="Вход и регистрация">
        <NavigationLink to="/login" navigate={navigate}>{ru.loginAction}</NavigationLink>
        <NavigationLink to="/register" navigate={navigate}>{ru.register}</NavigationLink>
      </nav>
    </main>
  )
}
