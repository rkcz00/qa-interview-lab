import { ApiError } from '../api/client.ts'
import type { ApiClient } from '../api/client.ts'
import type { Language, Progress, Result, SubmittedAttempt, TopicSummary } from '../api/types.ts'
import { publicResult } from '../assessment/answers.ts'
import { learningFailure } from '../learning/model.ts'
import { progressRu as text } from './texts.ts'

interface TopicState { readAt: string | null; mastered: boolean; bestResult: Result | null }
export interface TopicRow {
  topicId: string
  title: string
  titleLanguage: Language
  titleSource: 'catalog' | 'history' | 'unavailable'
  available: boolean
  progress: TopicState | null
}
export interface HistoryRow {
  attemptId: string
  topicId: string
  title: string
  language: Language
  submittedAt: string
  result: Result
}
export interface ProgressView { topics: TopicRow[]; history: HistoryRow[]; hasSavedProgress: boolean }

export function progressView(catalog: readonly TopicSummary[], progress: readonly Progress[], history: readonly SubmittedAttempt[]): ProgressView {
  const titles = new Map(catalog.map(topic => [topic.topic_id, topic.title]))
  const states = new Map(progress.map(item => [item.topic_id, item]))
  const historical = new Map<string, SubmittedAttempt>()
  for (const attempt of history) if (!historical.has(attempt.topic_id)) historical.set(attempt.topic_id, attempt)
  // Preserve the catalog order, followed by saved topics absent from the catalog.
  const ids = [...new Set([...catalog.map(topic => topic.topic_id), ...progress.map(item => item.topic_id), ...history.map(item => item.topic_id)])]
  return {
    topics: ids.map(topicId => {
      const state = states.get(topicId)
      const attempt = historical.get(topicId)
      const available = titles.has(topicId)
      return {
        topicId,
        title: available ? titles.get(topicId)! : attempt?.topic_title ?? `Тема № ${topicId}`,
        titleLanguage: available ? 'ru' : attempt?.submitted_language ?? 'ru',
        titleSource: available ? 'catalog' : attempt ? 'history' : 'unavailable',
        available,
        progress: state ? { readAt: state.article_read_at, mastered: state.mastered,
          bestResult: state.best_result ? publicResult(state.best_result) : null } :
          attempt ? null : { readAt: null, mastered: false, bestResult: null },
      }
    }),
    history: history.map(attempt => ({ attemptId: attempt.attempt_id, topicId: attempt.topic_id,
      title: attempt.topic_title, language: attempt.submitted_language, submittedAt: attempt.submitted_at,
      result: publicResult(attempt.result) })),
    hasSavedProgress: progress.length > 0 || history.length > 0,
  }
}

export function attemptDate(value: string): { text: string; iso?: string } {
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return { text: text.invalidDate }
  return { text: new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }).format(date), iso: date.toISOString() }
}

type ProgressApi = {
  learning: Pick<ApiClient['learning'], 'catalog'>
  progress: Pick<ApiClient['progress'], 'current'>
  assessment: Pick<ApiClient['assessment'], 'history'>
}
export type ProgressState = { kind: 'loading' | 'authentication' } | { kind: 'ready'; view: ProgressView } | { kind: 'error'; message: string }

export class ProgressStore {
  #api: ProgressApi
  #state: ProgressState = { kind: 'loading' }
  #listeners = new Set<() => void>()
  #generation = 0
  constructor(api: ProgressApi) { this.#api = api }
  getSnapshot = () => this.#state
  subscribe = (listener: () => void) => { this.#listeners.add(listener); return () => { this.#listeners.delete(listener) } }
  #publish(state: ProgressState) { this.#state = state; for (const listener of this.#listeners) listener() }
  invalidate = () => { this.#generation++ }
  async load() {
    const generation = ++this.#generation
    this.#publish({ kind: 'loading' })
    const guarded = <T,>(request: Promise<T>) => request.catch((error: unknown) => {
      if (generation === this.#generation && learningFailure(error) === 'authentication') {
        this.invalidate(); this.#publish({ kind: 'authentication' })
      }
      throw error
    })
    try {
      const [catalog, progress, history] = await Promise.all([
        guarded(this.#api.learning.catalog('ru')), guarded(this.#api.progress.current()), guarded(this.#api.assessment.history()),
      ])
      if (generation !== this.#generation) return
      this.#publish({ kind: 'ready', view: progressView(catalog, progress, history) })
    } catch (error) {
      if (generation !== this.#generation) return
      const message = error instanceof ApiError && error.status === 404 ? text.notFound :
        error instanceof ApiError && error.status === 403 ? text.forbidden :
        learningFailure(error) === 'network' ? text.network : text.server
      this.#publish({ kind: 'error', message })
    }
  }
}
