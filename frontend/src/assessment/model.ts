import { ApiError } from '../api/client.ts'
import type { ApiClient } from '../api/client.ts'
import type { Answer, Attempt, Language, PendingAttempt, Result, SubmittedAttempt } from '../api/types.ts'
import { learningFailure } from '../learning/model.ts'
import { answerPayload, publicResult, questionStructure, selectChoice } from './answers.ts'
import type { Selection } from './answers.ts'
import { assessmentRu as text } from './texts.ts'

export function assessmentFailure(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 400 && error.code === 'validation_error') return 'validation'
    if (error.status === 409 && error.code === 'attempt_already_submitted') return 'conflict'
  }
  return learningFailure(error)
}

class Observable<T> {
  #state: T
  #listeners = new Set<() => void>()
  constructor(initial: T) { this.#state = initial }
  getSnapshot = () => this.#state
  subscribe = (listener: () => void) => {
    this.#listeners.add(listener)
    return () => { this.#listeners.delete(listener) }
  }
  protected publish(state: T) { this.#state = state; for (const listener of this.#listeners) listener() }
}

export type StartState = { kind: 'loading' | 'creating' | 'authentication' | 'not_found'; language: Language } |
  { kind: 'ready'; language: Language; title: string; message?: string } |
  { kind: 'started'; language: Language; attemptId: string } |
  { kind: 'error' | 'uncertain'; language: Language; message: string }

type StartApi = { assessment: Pick<ApiClient['assessment'], 'start'>; learning: Pick<ApiClient['learning'], 'article'> }

export class StartStore extends Observable<StartState> {
  #api: StartApi
  #topicId: string
  #generation = 0
  #title = ''
  constructor(api: StartApi, topicId: string) {
    super({ kind: 'loading', language: 'ru' }); this.#api = api; this.#topicId = topicId
  }
  invalidate = () => { this.#generation++ }
  async load(language: Language) {
    if (['creating', 'uncertain', 'started'].includes(this.getSnapshot().kind)) return
    const generation = ++this.#generation
    this.publish({ kind: 'loading', language })
    try {
      const article = await this.#api.learning.article(this.#topicId, language)
      if (generation !== this.#generation) return
      if (article.topic_id !== this.#topicId || article.language !== language) throw new Error('Unexpected topic response')
      this.#title = article.title
      this.publish({ kind: 'ready', title: article.title, language })
    } catch (error) {
      if (generation !== this.#generation) return
      const failure = assessmentFailure(error)
      if (failure === 'authentication' || failure === 'not_found') this.publish({ kind: failure, language })
      else this.publish({ kind: 'error', language, message: failure === 'network' ? text.network : text.server })
    }
  }
  async start(explicitNewAttempt = false) {
    const state = this.getSnapshot()
    if (state.kind !== 'ready' && !(state.kind === 'uncertain' && explicitNewAttempt)) return
    const generation = ++this.#generation
    const language = state.language
    this.publish({ kind: 'creating', language })
    try {
      const attempt = await this.#api.assessment.start(this.#topicId, language)
      if (generation !== this.#generation) return
      if (attempt.topic_id !== this.#topicId) throw new Error('Unexpected attempt response')
      this.publish({ kind: 'started', attemptId: attempt.attempt_id, language })
    } catch (error) {
      if (generation !== this.#generation) return
      const failure = assessmentFailure(error)
      if (failure === 'authentication' || failure === 'not_found') this.publish({ kind: failure, language })
      else if (failure === 'validation' || failure === 'csrf') {
        this.publish({ kind: 'ready', title: this.#title, language, message: failure === 'csrf' ? text.csrf : text.validation })
      } else this.publish({ kind: 'uncertain', language, message: text.startUncertain })
    }
  }
}

export type AttemptState = { kind: 'loading' | 'sending' | 'checking' | 'authentication' | 'not_found' } |
  { kind: 'pending'; attempt: PendingAttempt; selected: Selection; index: number; message?: string } |
  { kind: 'result'; result: Result; notice?: string } |
  { kind: 'error'; message: string } |
  { kind: 'uncertain'; message: string; canRetry: boolean }

type FrozenSubmission = { readonly language: Language; readonly answers: readonly Answer[] }

export class AttemptStore extends Observable<AttemptState> {
  #api: ApiClient['assessment']
  #id: string
  #generation = 0
  #draft: PendingAttempt | null = null
  #selected: Selection = new Map()
  #index = 0
  #language: Language = 'ru'
  #frozen: FrozenSubmission | null = null
  #writing = false
  #uncertain = false
  #conflict = false
  #message: string = text.submitUncertain
  constructor(api: ApiClient['assessment'], attemptId: string) { super({ kind: 'loading' }); this.#api = api; this.#id = attemptId }
  invalidate = () => { this.#generation++ }
  #clearDraft() { this.#draft = null; this.#selected = new Map(); this.#index = 0 }
  #terminal(kind: 'authentication' | 'not_found') {
    this.invalidate(); this.#clearDraft(); this.#frozen = null; this.#writing = false; this.publish({ kind })
  }
  #identity(attempt: Attempt) {
    if (attempt.attempt_id !== this.#id || (this.#draft && this.#draft.topic_id !== attempt.topic_id)) throw new Error('Unexpected attempt identity')
  }
  #finish(attempt: SubmittedAttempt) {
    this.#identity(attempt)
    const result = publicResult(attempt.result)
    const notice = this.#conflict ? text.conflict : undefined
    this.invalidate(); this.#clearDraft(); this.#frozen = null; this.#writing = false
    this.publish({ kind: 'result', result, notice })
  }
  #pending(message?: string) {
    if (this.#draft) this.publish({ kind: 'pending', attempt: this.#draft, selected: this.#selected, index: this.#index, message })
  }
  async load(language: Language) {
    if (this.#writing) return
    if (this.#frozen || this.#conflict) { await this.checkResult(); return }
    const generation = ++this.#generation
    this.#language = language
    this.publish({ kind: 'loading' })
    try {
      const attempt = await this.#api.get(this.#id, language)
      if (generation !== this.#generation) return
      this.#identity(attempt)
      if (attempt.status === 'submitted') { this.#finish(attempt); return }
      if (attempt.language !== language || attempt.questions.length === 0 ||
          (this.#draft && questionStructure(this.#draft) !== questionStructure(attempt))) throw new Error('Unexpected attempt content')
      this.#draft = attempt
      this.#pending()
    } catch (error) {
      if (generation !== this.#generation) return
      const failure = assessmentFailure(error)
      if (failure === 'authentication' || failure === 'not_found') this.#terminal(failure)
      else this.publish({ kind: 'error', message: failure === 'network' ? text.network : text.server })
    }
  }
  choose(questionId: string, choiceId: string, checked: boolean) {
    if (this.getSnapshot().kind !== 'pending' || !this.#draft) return
    try { this.#selected = selectChoice(this.#draft, this.#selected, questionId, choiceId, checked); this.#pending() }
    catch (error) { if (error instanceof RangeError) this.#pending(text.validation); else throw error }
  }
  move(index: number) {
    if (this.getSnapshot().kind !== 'pending' || !this.#draft || !Number.isInteger(index) || index < 0 || index >= this.#draft.questions.length) return
    this.#index = index; this.#pending()
  }
  clear() {
    if (this.getSnapshot().kind !== 'pending' || !this.#draft) return
    const next = new Map(this.#selected)
    next.delete(this.#draft.questions[this.#index].question_id)
    this.#selected = next; this.#pending()
  }
  async submit() {
    if (this.getSnapshot().kind !== 'pending' || !this.#draft || this.#writing) return
    try { this.#frozen = Object.freeze({ language: this.#draft.language, answers: answerPayload(this.#draft, this.#selected) }) }
    catch (error) { if (error instanceof RangeError) this.#pending(text.validation); else throw error; return }
    await this.#write()
  }
  async retrySame() {
    const state = this.getSnapshot()
    if (state.kind !== 'uncertain' || !state.canRetry || !this.#frozen || this.#conflict) return
    await this.#write()
  }
  async #write() {
    if (this.#writing || !this.#frozen) return
    const frozen = this.#frozen
    const generation = ++this.#generation
    this.#writing = true
    this.publish({ kind: 'sending' })
    try {
      const result = await this.#api.submit(this.#id, frozen.language, frozen.answers)
      if (generation === this.#generation) this.#finish(result)
    } catch (error) {
      if (generation !== this.#generation) return
      this.#writing = false
      const failure = assessmentFailure(error)
      if (failure === 'authentication' || failure === 'not_found') { this.#terminal(failure); return }
      if (!this.#uncertain && (failure === 'validation' || failure === 'csrf')) {
        this.#frozen = null; this.#pending(failure === 'csrf' ? text.csrf : text.validation); return
      }
      this.#uncertain = true
      if (failure === 'conflict') { this.#conflict = true; this.#frozen = null; this.#message = text.conflictPending }
      else this.#message = failure === 'csrf' ? text.csrf : failure === 'validation' ? text.validation : text.submitUncertain
      this.#clearDraft()
      await this.checkResult()
    } finally { if (generation === this.#generation) this.#writing = false }
  }
  async checkResult() {
    if (this.#writing || this.getSnapshot().kind === 'checking') return
    const generation = ++this.#generation
    this.publish({ kind: 'checking' })
    try {
      const attempt = await this.#api.get(this.#id, this.#frozen?.language ?? this.#language)
      if (generation !== this.#generation) return
      this.#identity(attempt)
      if (attempt.status === 'submitted') this.#finish(attempt)
      else this.publish({ kind: 'uncertain', message: this.#message, canRetry: Boolean(this.#frozen && !this.#conflict) })
    } catch (error) {
      if (generation !== this.#generation) return
      const failure = assessmentFailure(error)
      if (failure === 'authentication' || failure === 'not_found') this.#terminal(failure)
      else this.publish({ kind: 'uncertain', message: this.#message, canRetry: false })
    }
  }
}
