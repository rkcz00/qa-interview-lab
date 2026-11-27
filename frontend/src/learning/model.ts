import { ApiError } from '../api/client.ts'
import type { ApiClient } from '../api/client.ts'
import type { SectionsArticle, Term, TopicSummary } from '../api/types.ts'
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
  { kind: 'topic'; article: SectionsArticle; terms: Term[] } | { kind: 'not_found' } |
  { kind: 'authentication' } | { kind: 'error'; message: string }
export type Read = { kind: 'loading' } | { kind: 'ready'; complete: boolean; sections: Readonly<Record<string, string | null>>; pending: boolean } |
  { kind: 'error'; message: string }
export interface LearningState { content: Content; read: Read }
export type LearningApi = { learning: Pick<ApiClient['learning'], 'catalog' | 'sections' | 'terms' | 'reading'>; progress: Pick<ApiClient['progress'], 'markSectionRead'> }

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
  #fail(failure: Failure, clearRead = false) {
    this.#generation++
    const content: Content = failure === 'authentication' ? { kind: 'authentication' } :
      failure === 'not_found' ? { kind: 'not_found' } :
      { kind: 'error', message: failure === 'network' ? text.networkError : text.serverError }
    if (clearRead || failure === 'authentication') {
      this.#readGeneration++
      this.#publish({ content, read: { kind: 'loading' } })
    } else {
      // A failed translation does not cancel or reset the independent read request.
      this.#publish({ content })
    }
  }

  async load(location: LearningLocation = this.#location) {
    const sameTopic = location.topicId !== null && location.topicId === this.#location.topicId
    const keepRead = sameTopic && this.#state.read.kind !== 'loading'
    if (!sameTopic) this.#readGeneration++
    this.#location = location
    const generation = ++this.#generation
    this.#publish({ content: { kind: 'loading' }, read: keepRead ? this.#state.read : { kind: 'loading' } })
    const { topicId, language } = this.#location
    try {
      if (topicId === null) {
        const topics = await this.#api.learning.catalog(language)
        if (generation === this.#generation) this.#publish({ content: { kind: 'catalog', topics } })
      } else {
        if (!keepRead) void this.#loadRead()
        const [article, terms] = await Promise.all([
          this.#api.learning.sections(topicId, language), this.#api.learning.terms(topicId, language),
        ])
        if (generation !== this.#generation) return
        if (article.topic_id !== topicId || article.language !== language || terms.some(term => term.language !== language)) {
          this.#fail('server')
          return
        }
        this.#publish({ content: { kind: 'topic', article, terms } })
        const read = this.#state.read
        if (read.kind === 'ready' && !read.pending &&
            (article.sections.length !== Object.keys(read.sections).length ||
             article.sections.some(section => !Object.hasOwn(read.sections, section.section_id)))) void this.#loadRead()
      }
    } catch (error) { if (generation === this.#generation) this.#fail(learningFailure(error)) }
  }

  async #loadRead() {
    const topicId = this.#location.topicId
    if (topicId === null || (this.#state.read.kind === 'ready' && this.#state.read.pending)) return
    const readGeneration = ++this.#readGeneration
    this.#publish({ read: { kind: 'loading' } })
    try {
      const progress = await this.#api.learning.reading(topicId)
      if (topicId !== this.#location.topicId || readGeneration !== this.#readGeneration) return
      if (progress.topic_id !== topicId) throw new Error('Unexpected reading identity')
      this.#publish({ read: { kind: 'ready', complete: progress.reading.is_read, pending: false,
        sections: Object.fromEntries(progress.sections.map(section => [section.section_id, section.read_at])) } })
    } catch (error) {
      if (topicId !== this.#location.topicId || readGeneration !== this.#readGeneration) return
      const failure = learningFailure(error)
      if (failure === 'authentication') this.#fail(failure)
      else this.#publish({ read: { kind: 'error', message: text.readError } })
    }
  }
  refreshRead() { return this.#loadRead() }

  async markRead(sectionId?: string) {
    const { content, read } = this.#state
    if (content.kind !== 'topic' || read.kind !== 'ready' || read.complete || read.pending || this.#location.topicId === null) return
    sectionId ??= content.article.sections.length === 1 ? content.article.sections[0].section_id : undefined
    if (!sectionId || read.sections[sectionId] !== null || !content.article.sections.some(section => section.section_id === sectionId)) return
    const topicId = this.#location.topicId
    const readGeneration = ++this.#readGeneration
    this.#publish({ read: { ...read, pending: true } })
    try {
      const progress = await this.#api.progress.markSectionRead(topicId, sectionId)
      if (topicId !== this.#location.topicId || readGeneration !== this.#readGeneration) return
      if (progress.topic_id !== topicId || progress.section_id !== sectionId || !progress.read_at) {
        this.#publish({ read: { kind: 'error', message: text.readError } })
        return
      }
      const sections = { ...read.sections, [sectionId]: progress.read_at }
      this.#publish({ read: { kind: 'ready', complete: progress.reading.is_read, sections, pending: false } })
      if (progress.reading.total_sections !== Object.keys(sections).length) void this.#loadRead()
    } catch (error) {
      if (topicId !== this.#location.topicId || readGeneration !== this.#readGeneration) return
      const failure = learningFailure(error)
      if (failure === 'authentication' || failure === 'not_found') this.#fail(failure, true)
      else this.#publish({ read: { kind: 'error', message: failure === 'csrf' ? text.csrfError : text.readError } })
    }
  }
}
