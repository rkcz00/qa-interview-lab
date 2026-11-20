import type { Language } from '../api/types.ts'
import type { Destination, PracticeRoute, Route } from '../auth/routing.ts'

export interface PracticeLocation { kind: 'preview' | 'submission'; id: string; language: Language }
export function isPracticeRoute(route: Route | null): route is PracticeRoute {
  return Boolean(route && (/^\/topics\/[^/?#]+\/practice$/u.test(route) || /^\/practice-submissions\/[^/?#]+$/u.test(route)))
}
export function practiceLocation(route: Route, search: string): PracticeLocation | null {
  if (!isPracticeRoute(route)) return null
  const query = new URLSearchParams(search)
  const languages = query.getAll('language')
  const language = languages.length === 0 ? 'ru' : languages[0]
  if ([...query.keys()].some(key => key !== 'language') || languages.length > 1 || (language !== 'ru' && language !== 'en')) return null
  try {
    const id = decodeURIComponent(route.split('/')[2])
    if (!id || id === '.' || id === '..' || /[/?#\\\u0000-\u001f]/u.test(id)) return null
    return { kind: route.startsWith('/practice-submissions/') ? 'submission' : 'preview', id, language }
  } catch { return null }
}
export function practiceDestination(location: PracticeLocation): Destination {
  const path: PracticeRoute = location.kind === 'preview' ? `/topics/${encodeURIComponent(location.id)}/practice` : `/practice-submissions/${encodeURIComponent(location.id)}`
  return location.language === 'ru' ? path : `${path}?language=en`
}
