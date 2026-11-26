import type { Language } from '../api/types.ts'
import type { Destination, LearningRoute, Route } from '../auth/routing.ts'

export interface LearningLocation {
  topicId: string | null
  language: Language
}

export function isLearningRoute(route: Route | null): route is LearningRoute {
  return route === '/topics' || Boolean(route && /^\/topics\/[^/?#]+$/u.test(route))
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

export function sectionFromHash(hash: string): string | null {
  return /^#section-[1-9][0-9]*$/u.test(hash) ? hash.slice('#section-'.length) : null
}

export function learningDestination(location: LearningLocation, sectionId: string | null = null): Destination {
  const path: LearningRoute = location.topicId === null ? '/topics' : `/topics/${encodeURIComponent(location.topicId)}`
  const destination = location.language === 'ru' ? path : `${path}?language=en` as const
  return location.topicId !== null && sectionId !== null && /^[1-9][0-9]*$/u.test(sectionId)
    ? `${destination}#section-${sectionId}` : destination
}

// Login always opens the home catalog; arbitrary return targets are never accepted.
export function authDestination(_pending?: Destination): Destination { return '/' }
