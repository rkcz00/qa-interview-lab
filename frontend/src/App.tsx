import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import type { Language } from './api/types.ts'
import { NavigationLink } from './auth/NavigationLink.tsx'
import { resolveRoute } from './auth/routing.ts'
import type { AuthRoute, Destination } from './auth/routing.ts'
import { ru } from './auth/texts.ts'
import { authDestination, isLearningRoute, learningDestination, learningLocation } from './learning/routing.ts'
import { learningRu } from './learning/texts.ts'
import { assessmentLocation, isAssessmentRoute } from './assessment/routing.ts'
import { assessmentRu } from './assessment/texts.ts'

const AuthApplication = lazy(() => import('./auth/AuthApplication.tsx'))
const LearningApplication = lazy(() => import('./learning/LearningApplication.tsx'))
const AssessmentApplication = lazy(() => import('./assessment/AssessmentApplication.tsx'))

export default function App() {
  const [address, setAddress] = useState(window.location.pathname + window.location.search)
  const [registeredEmail, setRegisteredEmail] = useState<string>()
  const [pendingLearning, setPendingLearning] = useState<Destination>()
  const articleLanguages = useRef(new Map<string, Language>())
  const [pathname, search = ''] = address.split('?')
  const route = resolveRoute(pathname)
  const learning = isLearningRoute(route) ? learningLocation(route, search) : null
  const assessment = route && isAssessmentRoute(route) ? assessmentLocation(route, search) : null
  const articleLink = useCallback((topicId: string) => learningDestination({ topicId, language: articleLanguages.current.get(topicId) ?? 'ru' }), [])
  useEffect(() => {
    if (learning?.topicId) articleLanguages.current.set(learning.topicId, learning.language)
  }, [learning?.topicId, learning?.language])
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
    document.title = route === '/' ? ru.brand : `${route === '/register' ? ru.register : route === '/login' ? ru.login : route === '/session' ? ru.session : isAssessmentRoute(route) ? assessmentRu.title : isLearningRoute(route) ? learningRu.catalog : ru.notFound} — ${ru.brand}`
  }, [route])

  if (isAssessmentRoute(route)) return assessment ? <Suspense fallback={<main><p role="status">{ru.checking}</p></main>}>
    <AssessmentApplication key={pathname} location={assessment} navigate={navigate} requireLogin={requireLogin} articleLink={articleLink} />
  </Suspense> : <main><h1>{assessmentRu.title}</h1><p role="alert">{assessmentRu.invalidRoute}</p><NavigationLink to="/topics" navigate={navigate}>{ru.topics}</NavigationLink></main>
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
