import { ApiError } from '../api/client.ts'
import type { ApiClient } from '../api/client.ts'
import type { Progress, TopicSummary } from '../api/types.ts'
import { learningFailure } from '../learning/model.ts'
import { progressRu as text } from './texts.ts'

export interface ProgressView {
  topics: TopicSummary[]
  total: number
  mastered: number
  percentage: number
}

export function progressView(catalog: readonly TopicSummary[], progress: readonly Progress[]): ProgressView {
  const topics = [...new Map(catalog.map(topic => [topic.topic_id, { topic_id: topic.topic_id, title: topic.title }])).values()]
  const masteredIds = new Set(progress.filter(item => item.mastered).map(item => item.topic_id))
  const mastered = topics.filter(topic => masteredIds.has(topic.topic_id)).length
  return { topics, total: topics.length, mastered,
    percentage: topics.length ? Math.round(mastered * 10000 / topics.length) / 100 : 0 }
}

type ProgressApi = {
  learning: Pick<ApiClient['learning'], 'catalog'>
  progress: Pick<ApiClient['progress'], 'current'>
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
  async load(background = false) {
    const generation = ++this.#generation
    if (!background || this.#state.kind !== 'ready') this.#publish({ kind: 'loading' })
    const guarded = <T,>(request: Promise<T>) => request.catch((error: unknown) => {
      if (generation === this.#generation && learningFailure(error) === 'authentication') {
        this.invalidate(); this.#publish({ kind: 'authentication' })
      }
      throw error
    })
    try {
      const [catalog, progress] = await Promise.all([
        guarded(this.#api.learning.catalog('ru')), guarded(this.#api.progress.current()),
      ])
      if (generation !== this.#generation) return
      this.#publish({ kind: 'ready', view: progressView(catalog, progress) })
    } catch (error) {
      if (generation !== this.#generation) return
      const message = error instanceof ApiError && error.status === 404 ? text.notFound :
        error instanceof ApiError && error.status === 403 ? text.forbidden :
        learningFailure(error) === 'network' ? text.network : text.server
      this.#publish({ kind: 'error', message })
    }
  }
}
