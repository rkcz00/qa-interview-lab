import type { Language } from '../api/types.ts'
import type { AssessmentRoute, Destination, Route } from '../auth/routing.ts'

export type AssessmentLocation = { kind: 'start'; id: string; language: Language } |
  { kind: 'attempt'; id: string; language: Language }

export function isAssessmentRoute(route: Route | null): route is AssessmentRoute {
  return Boolean(route && (/^\/topics\/[^/?#]+\/test$/u.test(route) || /^\/attempts\/[^/?#]+$/u.test(route)))
}

export function assessmentLocation(route: Route, search: string): AssessmentLocation | null {
  if (!isAssessmentRoute(route)) return null
  const values = new URLSearchParams(search).getAll('language')
  const language = values.length === 0 ? 'ru' : values[0]
  if (values.length > 1 || (language !== 'ru' && language !== 'en')) return null
  const kind = route.startsWith('/attempts/') ? 'attempt' : 'start'
  const segment = route.split('/')[2]
  try {
    const id = decodeURIComponent(segment)
    if (!id || id === '.' || id === '..' || /[/?#\\\u0000-\u001f]/u.test(id)) return null
    return { kind, id, language }
  } catch { return null }
}

export function assessmentDestination(location: AssessmentLocation): Destination {
  const path: AssessmentRoute = location.kind === 'start' ? `/topics/${encodeURIComponent(location.id)}/test` : `/attempts/${encodeURIComponent(location.id)}`
  return location.language === 'ru' ? path : `${path}?language=en`
}
