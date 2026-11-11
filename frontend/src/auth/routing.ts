export const routes = ['/', '/register', '/login', '/session'] as const
export type Route = typeof routes[number]
export function resolveRoute(pathname: string): Route | null {
  return routes.find(route => route === pathname) ?? null
}
