import type { Language } from '../api/types.ts'
import type { Destination, LearningRoute, Route } from '../auth/routing.ts'

// Authentication keeps its fixed home destination; external return targets are ignored.
export function authDestination(_pending?: Destination): Destination { return '/' }

export interface LearningLocation {
  topicId: string | null
  sectionId?: string | null
  language: Language
}

export function isLearningRoute(route: Route | null): route is LearningRoute {
  return route === '/topics' || Boolean(route && /^\/topics\/[^/?#]+(?:\/sections\/[^/?#]+)?$/u.test(route))
}

function routeId(value: string): string | null {
  try {
    const id = decodeURIComponent(value)
    return id && id !== '.' && id !== '..' && !/[/?#\\\u0000-\u001f]/u.test(id) ? id : null
  } catch { return null }
}
export function learningLocation(route: LearningRoute, search: string): LearningLocation | null {
  const values = new URLSearchParams(search).getAll('language')
  const language = values.length === 0 ? 'ru' : values[0]
  if (values.length > 1 || (language !== 'ru' && language !== 'en')) return null
  if (route === '/topics') return { topicId: null, sectionId: null, language }
  const parts = route.slice('/topics/'.length).split('/')
  const topicId = routeId(parts[0])
  const sectionId = parts.length === 3 && parts[1] === 'sections' ? routeId(parts[2]) : null
  if (!topicId || (parts.length !== 1 && (parts.length !== 3 || !sectionId))) return null
  return { topicId, sectionId, language }
}

export function sectionFromHash(hash: string): string | null {
  return /^#section-[1-9][0-9]*$/u.test(hash) ? hash.slice('#section-'.length) : null
}

export function learningDestination(location: LearningLocation, selectedSection: string | null = location.sectionId ?? null): Destination {
  const base: LearningRoute = location.topicId === null ? '/topics' : `/topics/${encodeURIComponent(location.topicId)}`
  const path: LearningRoute = location.topicId !== null && selectedSection !== null && /^[1-9][0-9]*$/u.test(selectedSection)
    ? `${base}/sections/${selectedSection}` : base
  return location.language === 'ru' ? path : `${path}?language=en`
}
