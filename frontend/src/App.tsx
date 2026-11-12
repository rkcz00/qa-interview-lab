import { lazy, Suspense, useCallback, useEffect, useState } from 'react'
import { NavigationLink } from './auth/NavigationLink.tsx'
import { resolveRoute } from './auth/routing.ts'
import type { AuthRoute, Destination } from './auth/routing.ts'
import { ru } from './auth/texts.ts'
import { authDestination, isLearningRoute, learningLocation } from './learning/routing.ts'
import { learningRu } from './learning/texts.ts'

const AuthApplication = lazy(() => import('./auth/AuthApplication.tsx'))
const LearningApplication = lazy(() => import('./learning/LearningApplication.tsx'))

export default function App() {
  const [address, setAddress] = useState(window.location.pathname + window.location.search)
  const [registeredEmail, setRegisteredEmail] = useState<string>()
  const [pendingLearning, setPendingLearning] = useState<Destination>()
  const [pathname, search = ''] = address.split('?')
  const route = resolveRoute(pathname)
  const learning = isLearningRoute(route) ? learningLocation(route, search) : null
  const move = useCallback((target: Destination, replace = false) => {
    if (replace) window.history.replaceState(null, '', target)
    else window.history.pushState(null, '', target)
    setAddress(target)
  }, [])
  const navigate = useCallback((target: Destination, replace = false) => {
    setRegisteredEmail(undefined)
    if (target !== '/login' && target !== '/register') setPendingLearning(undefined)
    move(target, replace)
  }, [move])
  const requireLogin = useCallback((target: Destination) => {
    setPendingLearning(target)
    setRegisteredEmail(undefined)
    move('/login', true)
  }, [move])
  const onAuthenticated = useCallback(() => {
    const target = authDestination(pendingLearning)
    setPendingLearning(undefined)
    setRegisteredEmail(undefined)
    move(target, true)
  }, [pendingLearning, move])
  const onRegistered = useCallback((email: string) => {
    setRegisteredEmail(email)
    move('/login', true)
  }, [move])

  useEffect(() => {
    const changed = () => {
      setAddress(window.location.pathname + window.location.search)
      setRegisteredEmail(undefined)
      if (!['/login', '/register'].includes(window.location.pathname)) setPendingLearning(undefined)
    }
    window.addEventListener('popstate', changed)
    return () => window.removeEventListener('popstate', changed)
  }, [])
  useEffect(() => {
    document.title = route === '/' ? ru.brand : `${route === '/register' ? ru.register : route === '/login' ? ru.login : route === '/session' ? ru.session : isLearningRoute(route) ? learningRu.catalog : ru.notFound} — ${ru.brand}`
  }, [route])

  if (isLearningRoute(route)) return learning ? <Suspense fallback={<main><p role="status">{ru.checking}</p></main>}>
    <LearningApplication key={address} location={learning} navigate={navigate} requireLogin={requireLogin} />
  </Suspense> : <main><h1>{learningRu.topic}</h1><p role="alert">{learningRu.invalidLanguage}</p><NavigationLink to="/topics" navigate={navigate}>{ru.topics}</NavigationLink></main>
  if (route && route !== '/') return <Suspense fallback={<main><p role="status">{ru.checking}</p></main>}>
    <AuthApplication key={route} route={route as AuthRoute} navigate={navigate} registeredEmail={registeredEmail} onRegistered={onRegistered} onAuthenticated={onAuthenticated} />
  </Suspense>
  if (!route) return <main><h1>{ru.notFound}</h1><NavigationLink to="/" navigate={navigate}>{ru.home}</NavigationLink></main>
  return (
    <main>
      <p className="eyebrow">{ru.audience}</p>
      <h1>{ru.brand}</h1>
      <p>{ru.intro}</p>
      <nav className="home-actions" aria-label="Вход и регистрация">
        <NavigationLink to="/topics" navigate={navigate}>{ru.topics}</NavigationLink>
        <NavigationLink to="/login" navigate={navigate}>{ru.loginAction}</NavigationLink>
        <NavigationLink to="/register" navigate={navigate}>{ru.register}</NavigationLink>
      </nav>
    </main>
  )
}
