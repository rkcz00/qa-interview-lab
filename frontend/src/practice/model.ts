import { ApiError } from '../api/client.ts'
import type { ApiClient } from '../api/client.ts'
import type { Language, PracticePreview, PracticeSubmission, SubmittedPractice } from '../api/types.ts'
import { practiceRu as text } from './texts.ts'

export function answerLength(value: string) { return Array.from(value).length }
export function answerError(value: string): string | null {
  if (answerLength(value) > 5000) return text.limit
  if (Array.from(value).some(char => char === '\0' || (char.codePointAt(0)! >= 0xd800 && char.codePointAt(0)! <= 0xdfff))) return text.invalidText
  return null
}
export function practiceFailure(error: unknown) {
  if (error instanceof ApiError) {
    if (error.code === 'authentication_required') return 'authentication'
    if (error.status === 404) return 'not_found'
    if (error.code === 'practice_locked' || error.code === 'section_read_required') return 'locked'
    if (error.code === 'csrf_failed') return 'csrf'
    if (error.code === 'validation_error') return 'validation'
    if (error.code === 'practice_already_submitted') return 'conflict'
    if (error.kind === 'network') return 'network'
    if (error.status === 403) return 'forbidden'
  }
  return 'server'
}
function failureText(error: unknown) {
  const failure = practiceFailure(error)
  return failure === 'network' ? text.network : failure === 'csrf' ? text.csrf : failure === 'validation' ? text.validation : failure === 'forbidden' ? text.forbidden : text.server
}
class Observable<T> {
  #state: T
  #listeners = new Set<() => void>()
  constructor(initial: T) { this.#state = initial }
  getSnapshot = () => this.#state
  subscribe = (listener: () => void) => { this.#listeners.add(listener); return () => { this.#listeners.delete(listener) } }
  protected publish(state: T) { this.#state = state; for (const listener of this.#listeners) listener() }
}
type Api = ApiClient['practice']
export interface PreviewState {
  kind: 'loading' | 'ready' | 'creating' | 'started' | 'uncertain' | 'error' | 'not_found' | 'authentication'
  language: Language
  preview: PracticePreview | null
  message?: string
  submissionId?: string
}
export class PreviewStore extends Observable<PreviewState> {
  #generation = 0
  #api: Api
  #id: string
  constructor(api: Api, topicId: string) { super({ kind: 'loading', language: 'ru', preview: null }); this.#api = api; this.#id = topicId }
  invalidate = () => { this.#generation++ }
  async load(language: Language) {
    if (['creating', 'uncertain', 'started'].includes(this.getSnapshot().kind)) return
    const generation = ++this.#generation
    this.publish({ kind: 'loading', language, preview: null })
    try {
      const preview = await this.#api.preview(this.#id, language)
      if (generation !== this.#generation) return
      if (preview.topic_id !== this.#id || preview.language !== language) throw new Error('Unexpected practice identity')
      this.publish({ kind: 'ready', language, preview })
    } catch (error) {
      if (generation !== this.#generation) return
      const failure = practiceFailure(error)
      this.publish({ kind: failure === 'authentication' || failure === 'not_found' ? failure : 'error', language, preview: null, message: failureText(error) })
    }
  }
  async start(explicitNew = false) {
    const state = this.getSnapshot()
    if (!(state.kind === 'ready' && state.preview?.can_start) && !(state.kind === 'uncertain' && explicitNew)) return
    const generation = ++this.#generation
    this.publish({ ...state, kind: 'creating', message: undefined })
    try {
      const pending = await this.#api.start(this.#id, state.language)
      if (generation !== this.#generation) return
      if (pending.topic_id !== this.#id || pending.language !== state.language) throw new Error('Unexpected practice identity')
      this.publish({ ...state, kind: 'started', submissionId: pending.submission_id })
    } catch (error) {
      if (generation !== this.#generation) return
      const failure = practiceFailure(error)
      if (failure === 'authentication' || failure === 'not_found') this.publish({ ...state, kind: failure, preview: null })
      else if (failure === 'locked') { this.publish({ ...state, kind: 'error' }); await this.load(state.language) }
      else if (failure === 'csrf' || failure === 'validation' || failure === 'forbidden') this.publish({ ...state, kind: 'ready', message: failureText(error) })
      else this.publish({ ...state, kind: 'uncertain', message: text.startUncertain })
    }
  }
}
export interface SubmissionState {
  kind: 'loading' | 'ready' | 'sending' | 'checking' | 'uncertain' | 'result' | 'restarting' | 'restart_uncertain' | 'restarted' | 'deleting' | 'delete_uncertain' | 'deleted' | 'error' | 'authentication' | 'not_found'
  item: PracticeSubmission | null
  answer: string
  message?: string
  canRetry?: boolean
  deletedTopic?: string | null
  fieldError?: boolean
  nextSubmission?: { id: string; language: Language }
  restartBlocked?: boolean
}
export class SubmissionStore extends Observable<SubmissionState> {
  #api: Api
  #id: string
  #generation = 0
  #language: Language = 'ru'
  #frozen: Readonly<{ language: Language; answer: string }> | null = null
  #conflict = false
  #writing = false
  #deletePending = false
  #topic: string | null = null
  constructor(api: Api, id: string) { super({ kind: 'loading', item: null, answer: '' }); this.#api = api; this.#id = id }
  invalidate = () => { this.#generation++; this.#frozen = null; this.publish({ kind: 'loading', item: null, answer: '' }) }
  #terminal(kind: 'authentication' | 'not_found') { this.#generation++; this.#frozen = null; this.#writing = false; this.#deletePending = false; this.publish({ kind, item: null, answer: '' }) }
  #identity(item: PracticeSubmission) {
    if (item.submission_id !== this.#id || (this.#topic && this.#topic !== item.topic_id)) throw new Error('Unexpected practice identity')
    this.#topic = item.topic_id
  }
  #finish(item: SubmittedPractice) {
    this.#identity(item); this.#frozen = null; this.#writing = false
    this.publish({ kind: 'result', item, answer: '', message: this.#conflict ? text.conflict : undefined })
  }
  setAnswer(answer: string) {
    if (this.getSnapshot().kind !== 'ready') return
    this.publish({ ...this.getSnapshot(), answer, message: undefined, fieldError: false })
  }
  async load(language: Language) {
    if (this.#writing || ['restart_uncertain', 'restarted'].includes(this.getSnapshot().kind)) return
    this.#language = language
    if (this.#deletePending) { await this.checkDelete(); return }
    if (this.#frozen || this.#conflict) { await this.check(); return }
    const generation = ++this.#generation
    this.publish({ ...this.getSnapshot(), kind: 'loading', message: undefined })
    try {
      const item = await this.#api.get(this.#id, language)
      if (generation !== this.#generation) return
      this.#identity(item)
      if (item.status === 'submitted') this.#finish(item)
      else {
        if (item.language !== language) throw new Error('Unexpected practice language')
        this.publish({ ...this.getSnapshot(), kind: 'ready', item })
      }
    } catch (error) { if (generation === this.#generation) this.#readFailure(error) }
  }
  #readFailure(error: unknown) {
    const failure = practiceFailure(error)
    if (failure === 'authentication' || failure === 'not_found') this.#terminal(failure)
    else this.publish({ ...this.getSnapshot(), kind: 'error', message: failureText(error) })
  }
  async submit() {
    const state = this.getSnapshot()
    if (state.kind !== 'ready' || state.item?.status !== 'in_progress' || this.#writing) return
    const problem = answerError(state.answer)
    if (problem) { this.publish({ ...state, message: problem, fieldError: true }); return }
    this.#frozen = Object.freeze({ language: state.item.language, answer: state.answer })
    await this.#write(false)
  }
  async retrySame() { if (this.getSnapshot().kind === 'uncertain' && this.getSnapshot().canRetry && this.#frozen) await this.#write(true) }
  async #write(wasUncertain: boolean) {
    if (this.#writing || !this.#frozen) return
    const frozen = this.#frozen
    const generation = ++this.#generation
    this.#writing = true
    this.publish({ ...this.getSnapshot(), kind: 'sending', message: undefined, canRetry: false, fieldError: false })
    try {
      const result = await this.#api.submit(this.#id, frozen.language, frozen.answer)
      if (generation === this.#generation) this.#finish(result)
    } catch (error) {
      if (generation !== this.#generation) return
      this.#writing = false
      const failure = practiceFailure(error)
      if (failure === 'authentication' || failure === 'not_found') { this.#terminal(failure); return }
      if (!wasUncertain && ['validation', 'csrf', 'forbidden'].includes(failure)) {
        this.#frozen = null; this.publish({ ...this.getSnapshot(), kind: 'ready', message: failureText(error), fieldError: failure === 'validation' }); return
      }
      if (failure === 'conflict') { this.#conflict = true; this.#frozen = null }
      await this.check()
    } finally { if (generation === this.#generation) this.#writing = false }
  }
  async check() {
    if (this.#writing || this.getSnapshot().kind === 'checking') return
    const generation = ++this.#generation
    this.publish({ ...this.getSnapshot(), kind: 'checking', canRetry: false })
    try {
      const item = await this.#api.get(this.#id, this.#frozen?.language ?? this.#language)
      if (generation !== this.#generation) return
      this.#identity(item)
      if (item.status === 'submitted') this.#finish(item)
      else this.publish({ ...this.getSnapshot(), kind: 'uncertain', message: this.#conflict ? text.conflictPending : text.uncertain, canRetry: Boolean(this.#frozen && !this.#conflict) })
    } catch (error) {
      if (generation !== this.#generation) return
      const failure = practiceFailure(error)
      if (failure === 'authentication' || failure === 'not_found') this.#terminal(failure)
      else this.publish({ ...this.getSnapshot(), kind: 'uncertain', message: text.uncertain, canRetry: false })
    }
  }
  async restart(explicitNew = false) {
    const state = this.getSnapshot()
    if (this.#writing || state.item?.status !== 'submitted' || state.restartBlocked ||
        !(state.kind === 'result' || (state.kind === 'restart_uncertain' && explicitNew))) return
    const language = state.item.submitted_language
    const generation = ++this.#generation
    this.#writing = true
    this.publish({ ...state, kind: 'restarting', message: undefined })
    try {
      const pending = await this.#api.start(state.item.topic_id, language)
      if (generation !== this.#generation) return
      if (pending.submission_id === this.#id || pending.topic_id !== state.item.topic_id || pending.language !== language) {
        throw new Error('Unexpected new practice identity')
      }
      this.publish({ ...state, kind: 'restarted', message: undefined, nextSubmission: { id: pending.submission_id, language } })
    } catch (error) {
      if (generation !== this.#generation) return
      const failure = practiceFailure(error)
      if (failure === 'authentication') this.#terminal(failure)
      else if (['not_found', 'locked', 'forbidden'].includes(failure)) {
        this.publish({ ...state, kind: 'result', restartBlocked: true, message: text.restartUnavailable })
      } else if (failure === 'csrf' || failure === 'validation') {
        this.publish({ ...state, kind: 'result', message: failureText(error) })
      } else this.publish({ ...state, kind: 'restart_uncertain', message: text.startUncertain })
    } finally { if (generation === this.#generation) this.#writing = false }
  }
  async remove(confirmed: boolean) {
    if (!confirmed || this.#writing || !['ready', 'result'].includes(this.getSnapshot().kind)) return
    await this.#delete()
  }
  async retryDelete() { if (this.getSnapshot().kind === 'delete_uncertain' && this.getSnapshot().canRetry) await this.#delete() }
  async #delete() {
    this.#writing = true; this.#deletePending = true
    const generation = ++this.#generation
    this.publish({ ...this.getSnapshot(), kind: 'deleting', message: undefined, canRetry: false })
    try {
      await this.#api.delete(this.#id)
      if (generation === this.#generation) await this.#deleted(generation)
    } catch (error) {
      if (generation !== this.#generation) return
      this.#writing = false
      const failure = practiceFailure(error)
      if (failure === 'authentication' || failure === 'not_found') { this.#terminal(failure); return }
      if (failure === 'csrf' || failure === 'validation' || failure === 'forbidden') {
        this.#deletePending = false
        this.publish({ ...this.getSnapshot(), kind: this.getSnapshot().item?.status === 'submitted' ? 'result' : 'ready', message: failureText(error) })
      } else await this.checkDelete()
    } finally { if (generation === this.#generation) this.#writing = false }
  }
  async #deleted(generation: number) {
    this.#frozen = null
    this.publish({ kind: 'deleting', item: null, answer: '' })
    let available: string | null = null
    try { if (this.#topic) { await this.#api.preview(this.#topic, this.#language); available = this.#topic } }
    catch (error) { if (practiceFailure(error) === 'authentication') { this.#terminal('authentication'); return } }
    if (generation !== this.#generation) return
    this.#deletePending = false; this.#writing = false
    this.publish({ kind: 'deleted', item: null, answer: '', deletedTopic: available })
  }
  async checkDelete() {
    if (this.#writing || this.getSnapshot().kind === 'checking') return
    const generation = ++this.#generation
    this.publish({ ...this.getSnapshot(), kind: 'checking', canRetry: false })
    try {
      const item = await this.#api.get(this.#id, this.#language)
      if (generation !== this.#generation) return
      this.#identity(item)
      this.publish({ ...this.getSnapshot(), kind: 'delete_uncertain', message: text.deleteUncertain, canRetry: true })
    } catch (error) {
      if (generation !== this.#generation) return
      const failure = practiceFailure(error)
      if (failure === 'authentication') this.#terminal(failure)
      else if (failure === 'not_found') await this.#deleted(generation)
      else this.publish({ ...this.getSnapshot(), kind: 'delete_uncertain', message: text.deleteUncertain, canRetry: false })
    }
  }
}
