import { ApiError } from '../api/client.ts'
import type { ApiClient } from '../api/client.ts'
import type { Article, Term, TopicSummary } from '../api/types.ts'
import type { LearningLocation } from './routing.ts'
import { learningRu as text } from './texts.ts'

type Failure = 'authentication' | 'not_found' | 'csrf' | 'network' | 'server'
export function learningFailure(error: unknown): Failure {
  if (!(error instanceof ApiError)) return 'server'
  if (error.status === 403 && error.code === 'authentication_required') return 'authentication'
  if (error.status === 404 && error.code === 'not_found') return 'not_found'
  if (error.status === 403 && error.code === 'csrf_failed') return 'csrf'
  if (error.code === 'network_error') return 'network'
  return 'server'
}

type Content = { kind: 'loading' } | { kind: 'catalog'; topics: TopicSummary[] } |
  { kind: 'topic'; article: Article; terms: Term[] } | { kind: 'not_found' } |
  { kind: 'authentication' } | { kind: 'error'; message: string }
type Read = { kind: 'loading' } | { kind: 'ready'; at: string | null; pending: boolean } |
  { kind: 'error'; message: string }
export interface LearningState { content: Content; read: Read }
type LearningApi = Pick<ApiClient, 'learning' | 'progress'>

export class LearningStore {
  #state: LearningState = { content: { kind: 'loading' }, read: { kind: 'loading' } }
  #listeners = new Set<() => void>()
  #generation = 0
  #readGeneration = 0
  #api: LearningApi
  #location: LearningLocation
  constructor(api: LearningApi, location: LearningLocation) { this.#api = api; this.#location = location }
  getSnapshot = () => this.#state
  subscribe = (listener: () => void) => {
    this.#listeners.add(listener)
    return () => { this.#listeners.delete(listener) }
  }
  #publish(next: Partial<LearningState>) {
    this.#state = { ...this.#state, ...next }
    for (const listener of this.#listeners) listener()
  }
  invalidate = () => { this.#generation++; this.#readGeneration++ }
  #fail(failure: Failure) {
    this.invalidate()
    const content: Content = failure === 'authentication' ? { kind: 'authentication' } :
      failure === 'not_found' ? { kind: 'not_found' } :
      { kind: 'error', message: failure === 'network' ? text.networkError : text.serverError }
    this.#publish({ content, read: { kind: 'loading' } })
  }

  async load() {
    const generation = ++this.#generation
    this.#readGeneration++
    this.#publish({ content: { kind: 'loading' }, read: { kind: 'loading' } })
    const { topicId, language } = this.#location
    try {
      if (topicId === null) {
        const topics = await this.#api.learning.catalog(language)
        if (generation === this.#generation) this.#publish({ content: { kind: 'catalog', topics } })
      } else {
        void this.#loadRead(generation)
        const [article, terms] = await Promise.all([
          this.#api.learning.article(topicId, language), this.#api.learning.terms(topicId, language),
        ])
        if (generation !== this.#generation) return
        if (article.topic_id !== topicId || article.language !== language || terms.some(term => term.language !== language)) {
          this.#fail('server')
          return
        }
        this.#publish({ content: { kind: 'topic', article, terms } })
      }
    } catch (error) { if (generation === this.#generation) this.#fail(learningFailure(error)) }
  }

  async #loadRead(generation: number) {
    const readGeneration = ++this.#readGeneration
    this.#publish({ read: { kind: 'loading' } })
    try {
      const progress = await this.#api.progress.current()
      if (generation !== this.#generation || readGeneration !== this.#readGeneration) return
      const at = progress.find(item => item.topic_id === this.#location.topicId)?.article_read_at ?? null
      this.#publish({ read: { kind: 'ready', at, pending: false } })
    } catch (error) {
      if (generation !== this.#generation || readGeneration !== this.#readGeneration) return
      const failure = learningFailure(error)
      if (failure === 'authentication') this.#fail(failure)
      else this.#publish({ read: { kind: 'error', message: text.readError } })
    }
  }
  refreshRead() { return this.#loadRead(this.#generation) }

  async markRead() {
    const { content, read } = this.#state
    if (content.kind !== 'topic' || read.kind !== 'ready' || read.at !== null || read.pending || this.#location.topicId === null) return
    const generation = this.#generation
    const readGeneration = ++this.#readGeneration
    this.#publish({ read: { ...read, pending: true } })
    try {
      const progress = await this.#api.progress.markRead(this.#location.topicId)
      if (generation !== this.#generation || readGeneration !== this.#readGeneration) return
      if (progress.topic_id !== this.#location.topicId || !progress.article_read_at) {
        this.#publish({ read: { kind: 'error', message: text.readError } })
        return
      }
      this.#publish({ read: { kind: 'ready', at: progress.article_read_at, pending: false } })
    } catch (error) {
      if (generation !== this.#generation || readGeneration !== this.#readGeneration) return
      const failure = learningFailure(error)
      if (failure === 'authentication' || failure === 'not_found') this.#fail(failure)
      else this.#publish({ read: { kind: 'error', message: failure === 'csrf' ? text.csrfError : text.readError } })
    }
  }
}
