import type { Language } from '../api/types.ts'
import type { Destination, LearningRoute, Route } from '../auth/routing.ts'

export interface LearningLocation {
  topicId: string | null
  language: Language
}

export function isLearningRoute(route: Route | null): route is LearningRoute {
  return route === '/topics' || Boolean(route?.startsWith('/topics/'))
}

export function learningLocation(route: LearningRoute, search: string): LearningLocation | null {
  const values = new URLSearchParams(search).getAll('language')
  const language = values.length === 0 ? 'ru' : values[0]
  if (values.length > 1 || (language !== 'ru' && language !== 'en')) return null
  if (route === '/topics') return { topicId: null, language }
  try {
    const topicId = decodeURIComponent(route.slice('/topics/'.length))
    if (!topicId || topicId === '.' || topicId === '..' || /[/?#\\\u0000-\u001f]/u.test(topicId)) return null
    return { topicId, language }
  } catch { return null }
}

export function learningDestination(location: LearningLocation): Destination {
  const path: LearningRoute = location.topicId === null ? '/topics' : `/topics/${encodeURIComponent(location.topicId)}`
  return location.language === 'ru' ? path : `${path}?language=en`
}

// Return targets come only from an already parsed Learning location, never from URL redirect parameters.
export function authDestination(pending: Destination | undefined): Destination {
  if (pending) {
    const [path, search = ''] = pending.split('?')
    if (isLearningRoute(path as Route)) {
      const location = learningLocation(path as LearningRoute, search)
      if (location) return learningDestination(location)
    }
  }
  return '/session'
}
