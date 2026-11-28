import { lazy, Suspense, useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import type { Language } from './api/types.ts'
import { NavigationLink } from './auth/NavigationLink.tsx'
import { ProtectedGate } from './auth/ProtectedGate.tsx'
import { resolveRoute } from './auth/routing.ts'
import type { Destination } from './auth/routing.ts'
import { ru } from './auth/texts.ts'
import { authDestination, isLearningRoute, learningDestination, learningLocation } from './learning/routing.ts'
import { learningRu } from './learning/texts.ts'
import { assessmentLocation, isAssessmentRoute } from './assessment/routing.ts'
import { assessmentRu } from './assessment/texts.ts'
import { progressRu } from './progress/texts.ts'
import { AppShell } from './ui/AppShell.tsx'
import { usePageHeadingFocus } from './ui/usePageHeadingFocus.ts'
import { LoadingState } from './ui/LoadingState.tsx'
import { Notice } from './ui/Notice.tsx'
import { isPracticeRoute, practiceLocation } from './practice/routing.ts'
import { practiceRu } from './practice/texts.ts'
import { allowHistoryNavigation } from './ui/navigation.ts'
import { api } from './api/index.ts'
import { SectionReads } from './learning/reading.ts'
import { ReadingContext } from './learning/ReadingContext.ts'
import { notifyProgressChanged } from './ui/OverviewContext.tsx'

const AuthApplication = lazy(() => import('./auth/AuthApplication.tsx'))
const LearningApplication = lazy(() => import('./learning/LearningApplication.tsx'))
const AssessmentApplication = lazy(() => import('./assessment/AssessmentApplication.tsx'))
const ProgressApplication = lazy(() => import('./progress/ProgressApplication.tsx'))
const PracticeApplication = lazy(() => import('./practice/PracticeApplication.tsx'))

export default function App() {
  const [address, setAddress] = useState(window.location.pathname + window.location.search + window.location.hash)
  const [registeredEmail, setRegisteredEmail] = useState<string>()
  const [reads] = useState(() => new SectionReads(api, notifyProgressChanged))
  const readingState = useSyncExternalStore(reads.subscribe, reads.getSnapshot)
  const articleLanguages = useRef(new Map<string, Language>())
  const hashAt = address.indexOf('#')
  const pageAddress = hashAt < 0 ? address : address.slice(0, hashAt)
  const hash = hashAt < 0 ? '' : address.slice(hashAt)
  const [pathname, search = ''] = pageAddress.split('?')
  const route = resolveRoute(pathname)
  const learning = route === '/' ? learningLocation('/topics', search) : isLearningRoute(route) ? learningLocation(route, search) : null
  const assessment = route && isAssessmentRoute(route) ? assessmentLocation(route, search) : null
  const practice = route && isPracticeRoute(route) ? practiceLocation(route, search) : null
  const staticHeading = usePageHeadingFocus(!route || ((route === '/' || isLearningRoute(route)) && !learning) || (isAssessmentRoute(route) && !assessment) || (isPracticeRoute(route) && !practice), pathname)
  const articleLanguage = useCallback((topicId: string) => articleLanguages.current.get(topicId) ?? 'ru', [])
  const articleLink = useCallback((topicId: string) => learningDestination({ topicId, language: articleLanguages.current.get(topicId) ?? 'ru' }), [])
  useEffect(() => { if (learning?.topicId) articleLanguages.current.set(learning.topicId, learning.language) }, [learning?.topicId, learning?.language])
  const move = useCallback((target: Destination, replace = false) => {
    if (replace) window.history.replaceState(null, '', target)
    else window.history.pushState(null, '', target)
    setAddress(target)
  }, [])
  const navigate = useCallback((target: Destination, replace = false) => { setRegisteredEmail(undefined); move(target, replace) }, [move])
  const requireLogin = useCallback((_target?: Destination) => { setRegisteredEmail(undefined); move('/login', true) }, [move])
  const onAuthenticated = useCallback(() => { setRegisteredEmail(undefined); move(authDestination(), true) }, [move])
  const onRegistered = useCallback((email: string) => { setRegisteredEmail(email); move('/login', true) }, [move])
  useEffect(() => {
    window.addEventListener('qil-reading-invalidated', reads.clear)
    return () => { window.removeEventListener('qil-reading-invalidated', reads.clear); reads.clear() }
  }, [reads])
  useEffect(() => { if (route === '/login' || route === '/register') reads.clear() }, [route, reads])
  useEffect(() => { if (readingState.expired) requireLogin() }, [readingState.expired, requireLogin])
  useEffect(() => {
    const changed = () => {
      if (!allowHistoryNavigation()) return
      setAddress(window.location.pathname + window.location.search + window.location.hash)
      setRegisteredEmail(undefined)
    }
    window.addEventListener('popstate', changed)
    window.addEventListener('hashchange', changed)
    return () => { window.removeEventListener('popstate', changed); window.removeEventListener('hashchange', changed) }
  }, [])
  useEffect(() => {
    document.title = `${route === '/register' ? ru.register : route === '/login' ? ru.login : route === '/session' ? ru.session : route === '/progress' ? progressRu.title : isPracticeRoute(route) ? practiceRu.title : isAssessmentRoute(route) ? assessmentRu.title : route === '/' || isLearningRoute(route) ? learningRu.catalog : ru.notFound} — ${ru.brand}`
  }, [route])

  const fallback = <main className="auth-shell"><LoadingState message={ru.checking} /></main>
  if (route === '/login' || route === '/register') return <Suspense fallback={fallback}>
    <AuthApplication key={route} route={route} navigate={navigate} registeredEmail={registeredEmail} onRegistered={onRegistered} onAuthenticated={onAuthenticated} />
  </Suspense>

  const page = route === '/session' ? <AuthApplication key={route} route={route} navigate={navigate} onRegistered={onRegistered} onAuthenticated={onAuthenticated} /> :
    route === '/progress' ? <ProgressApplication navigate={navigate} requireLogin={requireLogin} /> :
    isPracticeRoute(route) ? practice ? <PracticeApplication key={pathname} location={practice} navigate={navigate} requireLogin={requireLogin} /> :
      <AppShell navigate={navigate} canLogout><h1 ref={staticHeading} tabIndex={-1}>{practiceRu.title}</h1><Notice>{practiceRu.invalidRoute}</Notice></AppShell> :
    isAssessmentRoute(route) ? assessment ?
      <AssessmentApplication key={pathname} location={assessment} navigate={navigate} requireLogin={requireLogin} articleLink={articleLink} articleLanguage={articleLanguage} /> :
      <AppShell navigate={navigate} canLogout><h1 ref={staticHeading} tabIndex={-1}>{assessmentRu.title}</h1><Notice>{assessmentRu.invalidRoute}</Notice></AppShell> :
    route === '/' || isLearningRoute(route) ? learning ?
      <LearningApplication location={learning} hash={hash} navigate={navigate} requireLogin={requireLogin} /> :
      <AppShell navigate={navigate} canLogout><h1 ref={staticHeading} tabIndex={-1}>{learningRu.topic}</h1><Notice>{learningRu.invalidLanguage}</Notice></AppShell> :
      <AppShell navigate={navigate} canLogout><h1 ref={staticHeading} tabIndex={-1}>{ru.notFound}</h1><NavigationLink to="/" navigate={navigate}>{ru.home}</NavigationLink></AppShell>
  return <ReadingContext value={reads}><ProtectedGate requireLogin={requireLogin}><Suspense fallback={fallback}>{page}</Suspense></ProtectedGate></ReadingContext>
}
