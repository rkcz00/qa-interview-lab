export const routes = ['/', '/register', '/login', '/session'] as const
export type AuthRoute = Exclude<typeof routes[number], '/'>
export type LearningRoute = '/topics' | `/topics/${string}`
export type Route = typeof routes[number] | LearningRoute
export type Destination = Route | `${LearningRoute}?language=ru` | `${LearningRoute}?language=en`
export function resolveRoute(pathname: string): Route | null {
  if (pathname === '/topics' || /^\/topics\/[^/?#]+$/u.test(pathname)) return pathname as LearningRoute
  return routes.find(route => route === pathname) ?? null
}
