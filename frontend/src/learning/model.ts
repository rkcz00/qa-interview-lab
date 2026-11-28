import type { ApiClient } from '../api/client.ts'
import type { SectionArticle, Term, TopicReading, TopicSummary } from '../api/types.ts'
import type { LearningLocation } from './routing.ts'
import { learningFailure } from './failure.ts'
import { SectionReads } from './reading.ts'
import type { Read } from './reading.ts'
import { learningRu as text } from './texts.ts'

export { learningFailure } from './failure.ts'
export type { Read } from './reading.ts'
type Content = { kind: 'loading' } | { kind: 'catalog'; topics: TopicSummary[] } |
  { kind: 'topic'; topic: TopicReading; article: SectionArticle | null; terms: Term[] } |
  { kind: 'not_found' } | { kind: 'authentication' } | { kind: 'error'; message: string }
export interface LearningState { content: Content; read: Read }
export type LearningApi = { learning: Pick<ApiClient['learning'], 'catalog' | 'section' | 'terms' | 'reading'>;
  progress: Pick<ApiClient['progress'], 'markSectionRead'> }

export class LearningStore {
  #state: LearningState = { content: { kind: 'loading' }, read: { kind: 'loading' } }
  #listeners = new Set<() => void>()
  #registryUnsubscribe?: () => void
  #readVersion = -1
  #generation = 0
  #checkGeneration = 0
  #api: LearningApi
  #reads: SectionReads
  #location: LearningLocation
  #readError: string | null = null
  constructor(api: LearningApi, location: LearningLocation, reads: SectionReads) {
    this.#api = api; this.#location = location; this.#reads = reads
  }
  getSnapshot = () => {
    const current = this.#reads.getSnapshot()
    if (current.version !== this.#readVersion) {
      this.#readVersion = current.version
      const sectionId = this.#location.sectionId ?? null, topicId = this.#location.topicId
      const read = this.#reads.project(topicId, sectionId)
      const content: Content = current.expired ? { kind: 'authentication' } :
        topicId && sectionId && this.#reads.phase(topicId, sectionId) === 'unavailable' ? { kind: 'not_found' } : this.#state.content
      this.#readError = null
      this.#state = { content, read }
    }
    return this.#state
  }
  subscribe = (listener: () => void) => {
    this.#listeners.add(listener)
    this.#registryUnsubscribe ??= this.#reads.subscribe(() => {
      this.getSnapshot()
      for (const notify of this.#listeners) notify()
    })
    return () => {
      this.#listeners.delete(listener)
      if (!this.#listeners.size) { this.#registryUnsubscribe?.(); this.#registryUnsubscribe = undefined }
    }
  }
  #publish(content: Content) {
    this.getSnapshot()
    this.#state = { ...this.#state, content }
    for (const listener of this.#listeners) listener()
  }
  invalidate = () => { this.#generation++; this.#checkGeneration++ }
  async load(location: LearningLocation = this.#location) {
    if (!this.#reads.owner) return
    this.#location = location; this.#readVersion = -1; this.#readError = null
    const generation = ++this.#generation, token = this.#reads.token()
    this.#checkGeneration++
    this.#publish({ kind: 'loading' })
    const { topicId, language } = location, sectionId = location.sectionId ?? null
    try {
      if (topicId === null) {
        const topics = await this.#api.learning.catalog(language)
        if (generation === this.#generation && token.epoch === this.#reads.token().epoch) this.#publish({ kind: 'catalog', topics })
        return
      }
      const [topic, article, terms] = await Promise.all([
        this.#api.learning.reading(topicId, language),
        sectionId === null ? Promise.resolve(null) : this.#api.learning.section(topicId, sectionId, language),
        this.#api.learning.terms(topicId, language),
      ])
      if (generation !== this.#generation) return
      if (topic.topic_id !== topicId || topic.language !== language || terms.some(term => term.language !== language) ||
          (article !== null && (article.topic_id !== topicId || article.section.section_id !== sectionId || article.language !== language))) {
        this.#publish({ kind: 'error', message: text.serverError }); return
      }
      if (sectionId !== null && !topic.sections.some(section => section.section_id === sectionId)) {
        this.#publish({ kind: 'not_found' }); return
      }
      if (!this.#reads.accept(topic, token)) return
      this.#publish({ kind: 'topic', topic, article, terms })
    } catch (error) {
      if (generation !== this.#generation || token.epoch !== this.#reads.token().epoch) return
      const failure = learningFailure(error)
      if (failure === 'authentication') { this.#reads.expire(); this.#publish({ kind: 'authentication' }) }
      else this.#publish(failure === 'not_found' ? { kind: 'not_found' } :
        { kind: 'error', message: failure === 'network' ? text.networkError : text.serverError })
    }
  }
  async refreshRead() {
    const { topicId, sectionId } = this.#location
    if (!topicId || !this.#reads.owner || (sectionId && this.#reads.phase(topicId, sectionId) === 'pending')) return
    const generation = ++this.#checkGeneration, token = this.#reads.token()
    try {
      const value = await this.#api.learning.reading(topicId, this.#location.language)
      if (generation !== this.#checkGeneration || topicId !== this.#location.topicId) return
      if (value.topic_id !== topicId) throw new Error('Unexpected reading identity')
      this.#reads.accept(value, token, true)
    } catch (error) {
      if (generation !== this.#checkGeneration || token.epoch !== this.#reads.token().epoch) return
      if (learningFailure(error) === 'authentication') { this.#reads.expire(); this.#publish({ kind: 'authentication' }); return }
      this.#readError = text.readError
      this.#state = { ...this.#state, read: { kind: 'error', message: this.#readError } }
      for (const listener of this.#listeners) listener()
    }
  }
  markRead(sectionId: string | null = this.#location.sectionId ?? null) {
    const { content } = this.getSnapshot(), topicId = this.#location.topicId
    if (!topicId || !sectionId || sectionId !== this.#location.sectionId ||
        content.kind !== 'topic' || content.article?.section.section_id !== sectionId || this.#readError) return Promise.resolve()
    return this.#reads.mark(topicId, sectionId)
  }
  allowRetry() {
    const { topicId, sectionId } = this.#location
    if (topicId && sectionId && !this.#readError) this.#reads.allowRetry(topicId, sectionId)
  }
}
