import { ApiError } from '../api/client.ts'
import type { ApiClient } from '../api/client.ts'
import type { ReadingState, TopicReading } from '../api/types.ts'
import { learningFailure } from './failure.ts'
import { learningRu as text } from './texts.ts'

export type ReadPhase = 'unknown' | 'unread' | 'pending' | 'read' | 'error' | 'retry' | 'unavailable'
interface Entry {
  phase: ReadPhase; at: string | null; message?: string; changed: number; operation?: symbol
}
export interface ReadToken { epoch: number; mutation: number }
export type Read = { kind: 'loading' } | { kind: 'error'; message: string } |
  { kind: 'ready'; complete: boolean; reading: ReadingState; sections: Readonly<Record<string, string | null>>;
    pending: boolean; retryRequired?: true }
type ReadApi = { progress: Pick<ApiClient['progress'], 'markSectionRead'> }
interface TopicState { value: TopicReading }

// One instance above all reader pages; only public dates/state are retained in memory.
export class SectionReads {
  #owner: string | null = null
  #generation: string | null = null
  #epoch = 0
  #mutation = 0
  #entries = new Map<string, Entry>()
  #topics = new Map<string, TopicState>()
  #listeners = new Set<() => void>()
  #snapshot = { version: 0, expired: false }
  #api: ReadApi
  #saved: () => void
  constructor(api: ReadApi, saved: () => void = () => {}) { this.#api = api; this.#saved = saved }
  get owner() { return this.#owner }
  getSnapshot = () => this.#snapshot
  subscribe = (listener: () => void) => { this.#listeners.add(listener); return () => { this.#listeners.delete(listener) } }
  #emit(expired = this.#snapshot.expired) {
    this.#snapshot = { version: this.#snapshot.version + 1, expired }
    for (const listener of this.#listeners) listener()
  }
  clear = () => {
    this.#epoch++; this.#mutation++; this.#owner = null; this.#generation = null
    this.#entries.clear(); this.#topics.clear(); this.#emit(false)
  }
  expire() { this.clear(); this.#emit(true) }
  bindOwner(owner: string) {
    if (owner === this.#owner) return
    this.clear(); this.#owner = owner; this.#emit(false)
  }
  token(): ReadToken { return { epoch: this.#epoch, mutation: this.#mutation } }
  #key(topicId: string, sectionId: string) { return topicId + '/' + sectionId }
  phase(topicId: string, sectionId: string): ReadPhase {
    return this.#entries.get(this.#key(topicId, sectionId))?.phase ?? 'unknown'
  }
  accept(value: TopicReading, token: ReadToken, explicitCheck = false): boolean {
    if (!this.#owner || token.epoch !== this.#epoch) return false
    if (this.#generation !== null && value.progress_generation !== this.#generation) {
      if (BigInt(value.progress_generation) < BigInt(this.#generation)) return false
      // A new generation invalidates every old operation, even for another section.
      const owner = this.#owner
      this.clear(); this.#owner = owner
    }
    this.#generation = value.progress_generation
    const previous = this.#topics.get(value.topic_id)
    const sameSections = previous && previous.value.sections.length === value.sections.length &&
      value.sections.every(section => previous.value.sections.some(old => old.section_id === section.section_id))
    const reading = previous && sameSections && previous.value.reading.read_sections > value.reading.read_sections
      ? previous.value.reading : value.reading
    this.#topics.set(value.topic_id, { value: { ...value, reading } })
    let confirmedAfterError = false
    for (const section of value.sections) {
      const key = this.#key(value.topic_id, section.section_id), entry = this.#entries.get(key)
      if (entry?.phase === 'pending' || (entry && entry.changed > token.mutation)) continue
      if (entry?.at) continue // A stale GET cannot erase a confirmed first date.
      if (section.read_at !== null) {
        confirmedAfterError ||= entry?.phase === 'error' || entry?.phase === 'retry'
        this.#entries.set(key, { phase: 'read', at: section.read_at, changed: this.#mutation })
      } else if (entry?.phase === 'error' || entry?.phase === 'retry') {
        if (explicitCheck) this.#entries.set(key, { phase: 'retry', at: null, changed: this.#mutation })
      } else {
        this.#entries.set(key, { phase: 'unread', at: null, changed: this.#mutation })
      }
    }
    this.#emit()
    if (confirmedAfterError) this.#saved()
    return true
  }
  project(topicId: string | null, sectionId: string | null): Read {
    const topic = topicId === null ? undefined : this.#topics.get(topicId)
    if (!this.#owner || !topic || topicId === null) return { kind: 'loading' }
    const entry = sectionId === null ? undefined : this.#entries.get(this.#key(topicId, sectionId))
    if (entry?.phase === 'error') return { kind: 'error', message: entry.message ?? text.readError }
    if (sectionId !== null && (!entry || entry.phase === 'unknown')) return { kind: 'loading' }
    return { kind: 'ready', complete: topic.value.reading.is_read, reading: topic.value.reading,
      sections: Object.fromEntries(topic.value.sections.map(section => [section.section_id,
        this.#entries.get(this.#key(topicId, section.section_id))?.at ?? section.read_at])),
      pending: entry?.phase === 'pending',
      ...(entry?.phase === 'retry' ? { retryRequired: true as const } : {}) }
  }
  allowRetry(topicId: string, sectionId: string) {
    const entry = this.#entries.get(this.#key(topicId, sectionId))
    if (!this.#owner || entry?.phase !== 'retry') return
    entry.phase = 'unread'; entry.changed = ++this.#mutation; this.#emit()
  }
  mark(topicId: string, sectionId: string): Promise<void> {
    const entry = this.#entries.get(this.#key(topicId, sectionId))
    if (entry?.phase === 'pending') return Promise.resolve()
    if (!this.#owner || !this.#generation || entry?.phase !== 'unread') return Promise.resolve()
    const epoch = this.#epoch, generation = this.#generation, operation = Symbol('section-read')
    const publishedAtStart = this.#topics.get(topicId)?.value.sections.map(section => section.section_id).sort().join(',')
    entry.phase = 'pending'; entry.operation = operation; entry.changed = ++this.#mutation; this.#emit()
    const flight = (async () => {
      try {
        const value = await this.#api.progress.markSectionRead(topicId, sectionId, generation)
        if (epoch !== this.#epoch || entry.operation !== operation) return
        if (value.topic_id !== topicId || value.section_id !== sectionId || !value.read_at || value.progress_generation !== generation) {
          throw new Error('Unexpected section reading identity')
        }
        entry.at = value.read_at; entry.phase = 'read'; entry.changed = ++this.#mutation
        const topic = this.#topics.get(topicId)
        if (topic) {
          const earlier = topic.value.reading
          const sameSections = topic.value.sections.map(section => section.section_id).sort().join(',') === publishedAtStart
          const reading = !sameSections || (earlier.total_sections === value.reading.total_sections && earlier.read_sections > value.reading.read_sections)
            ? earlier : value.reading
          topic.value = { ...topic.value, reading }
        }
        this.#emit(); this.#saved()
      } catch (error) {
        if (epoch !== this.#epoch || entry.operation !== operation) return
        if (error instanceof ApiError && error.code === 'progress_reset') { this.clear(); return }
        const failure = learningFailure(error)
        if (failure === 'authentication') { this.expire(); return }
        entry.phase = failure === 'not_found' ? 'unavailable' : 'error'
        entry.message = failure === 'csrf' ? text.csrfError : text.readError
        entry.changed = ++this.#mutation; this.#emit()
      } finally {
        if (entry.operation === operation) entry.operation = undefined
      }
    })()
    return flight
  }
}
