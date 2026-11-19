import { resolveRoute } from '../auth/routing.ts'
import { ru } from '../auth/texts.ts'

export function learnerNavigation(pathname: string) {
  const route = resolveRoute(pathname)
  const section = route === '/session' ? '/session' : route === '/progress' ? '/progress' :
    route && (route === '/' || route.startsWith('/topics') || route.startsWith('/attempts/')) ? '/' : null
  return [
    { to: '/' as const, label: ru.topics },
    { to: '/progress' as const, label: ru.progress },
    { to: '/session' as const, label: ru.account },
  ].map(item => ({ ...item, current: section !== item.to ? undefined :
    route === item.to ? 'page' as const : 'location' as const }))
}
