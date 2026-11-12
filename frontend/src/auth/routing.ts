export const routes = ['/', '/register', '/login', '/session'] as const
export type AuthRoute = Exclude<typeof routes[number], '/'>
export type LearningRoute = '/topics' | `/topics/${string}`
export type AssessmentRoute = `/topics/${string}/test` | `/attempts/${string}`
export type Route = typeof routes[number] | LearningRoute | AssessmentRoute | '/progress'
export type Destination = Route | `${LearningRoute | AssessmentRoute}?language=ru` | `${LearningRoute | AssessmentRoute}?language=en`
export function resolveRoute(pathname: string): Route | null {
  if (pathname === '/progress') return '/progress'
  if (/^\/topics\/[^/?#]+\/test$/u.test(pathname) || /^\/attempts\/[^/?#]+$/u.test(pathname)) return pathname as AssessmentRoute
  if (pathname === '/topics' || /^\/topics\/[^/?#]+$/u.test(pathname)) return pathname as LearningRoute
  return routes.find(route => route === pathname) ?? null
}
