import { ApiError } from '../api/client.ts'
import type { ApiClient } from '../api/client.ts'
import type { CompletionProgress, TopicCompletion, TopicSummary } from '../api/types.ts'
import { learningFailure } from '../learning/model.ts'
import { progressRu as text } from './texts.ts'

export interface ProgressView {
  topics: (TopicCompletion & { title: string })[]
  navigationTopics: TopicSummary[]
  total: number
  mastered: number
  percentage: number
  generation: string
}

// Completion is authoritative for membership and percentages; catalog adds labels only.
export function progressView(catalog: readonly TopicSummary[], completion: CompletionProgress): ProgressView {
  const titles = new Map(catalog.map(topic => [topic.topic_id, topic.title]))
  const publishedIds = new Set(completion.topics.map(topic => topic.topic_id))
  const navigationTopics = catalog.filter(topic => publishedIds.has(topic.topic_id))
    .map(topic => ({ topic_id: topic.topic_id, title: topic.title }))
  const topics = completion.topics.map(topic => ({
    topic_id: topic.topic_id, title: titles.get(topic.topic_id) ?? text.untitled(topic.topic_id),
    article_read_at: topic.article_read_at,
    test: { status: topic.test.status, best_result: topic.test.best_result === null ? null : {
      correct_count: topic.test.best_result.correct_count, total_count: topic.test.best_result.total_count,
      percentage: topic.test.best_result.percentage,
    } },
    practice: topic.practice === null ? null : { task_id: topic.practice.task_id, status: topic.practice.status },
    completion_progress: topic.completion_progress, mastered: topic.mastered,
  }))
  return { topics, navigationTopics, total: topics.length, mastered: topics.filter(topic => topic.mastered).length,
    percentage: completion.overall_completion_progress, generation: completion.progress_generation }
}

type ProgressApi = {
  learning: Pick<ApiClient['learning'], 'catalog'>
  progress: Pick<ApiClient['progress'], 'completion' | 'reset'>
}
type Recovery = 'retry' | 'check' | 'refresh' | 'reload'
export type ResetState = { kind: 'idle' | 'success' | 'confirming' | 'posting' | 'refreshing' } |
  { kind: 'error'; message: string; action: Recovery; open: boolean }
type Ready = { kind: 'ready'; view: ProgressView; reset: ResetState; notice?: string }
export type ProgressState = { kind: 'loading' | 'authentication' } | Ready | { kind: 'error'; message: string }
type Receipt = { id: string; generation: string; acknowledged?: string; uncertain: boolean }

function loadError(error: unknown) {
  return error instanceof ApiError && error.status === 404 ? text.notFound :
    error instanceof ApiError && error.status === 403 ? text.forbidden :
    learningFailure(error) === 'network' ? text.network : text.server
}

export class ProgressStore {
  #api: ProgressApi
  #uuid: () => string
  #state: ProgressState = { kind: 'loading' }
  #listeners = new Set<() => void>()
  #generation = 0
  #receipt?: Receipt
  constructor(api: ProgressApi, uuid: () => string = () => crypto.randomUUID()) { this.#api = api; this.#uuid = uuid }
  getSnapshot = () => this.#state
  subscribe = (listener: () => void) => { this.#listeners.add(listener); return () => { this.#listeners.delete(listener) } }
  #publish(state: ProgressState) { this.#state = state; for (const listener of this.#listeners) listener() }
  invalidate = () => { this.#generation++ }
  ownsReset = () => this.#receipt !== undefined
  #reset(reset: ResetState) { if (this.#state.kind === 'ready') this.#publish({ ...this.#state, reset, notice: undefined }) }
  #authentication(error: unknown, generation: number) {
    if (generation === this.#generation && learningFailure(error) === 'authentication') {
      this.invalidate(); this.#receipt = undefined; this.#publish({ kind: 'authentication' })
    }
  }
  async #readView(generation: number) {
    const guarded = <T,>(request: Promise<T>) => request.catch((error: unknown) => {
      this.#authentication(error, generation)
      throw error
    })
    const [catalog, completion] = await Promise.all([
      guarded(this.#api.learning.catalog('ru')), guarded(this.#api.progress.completion()),
    ])
    return progressView(catalog, completion)
  }
  async load(background = false) {
    // Retain the receipt and frozen display while a destructive action is unresolved.
    if (this.#receipt || (this.#state.kind === 'ready' && this.#state.reset.kind === 'confirming')) return
    const generation = ++this.#generation
    if (!background || this.#state.kind !== 'ready') this.#publish({ kind: 'loading' })
    try {
      const view = await this.#readView(generation)
      if (generation === this.#generation) this.#publish({ kind: 'ready', view, reset: { kind: 'idle' } })
    } catch (error) {
      if (generation === this.#generation) this.#publish({ kind: 'error', message: loadError(error) })
    }
  }
  openReset = () => {
    if (this.#state.kind !== 'ready') return
    const reset = this.#state.reset
    if (reset.kind === 'posting' || reset.kind === 'refreshing') return
    this.#reset(reset.kind === 'error' && this.#receipt ? { ...reset, open: true } : { kind: 'confirming' })
  }
  cancelReset = () => {
    if (this.#state.kind !== 'ready') return
    const reset = this.#state.reset
    if (reset.kind === 'posting' || reset.kind === 'refreshing') return
    if (reset.kind === 'error' && this.#receipt && (reset.action === 'reload' || this.#receipt.uncertain || this.#receipt.acknowledged)) {
      this.#reset({ ...reset, open: false })
    } else {
      this.#receipt = undefined
      this.#reset({ kind: 'idle' })
    }
  }
  confirmReset = async () => {
    if (this.#state.kind !== 'ready' || this.#state.reset.kind !== 'confirming') return
    this.#receipt = { id: this.#uuid(), generation: this.#state.view.generation, uncertain: false }
    await this.#postReset()
  }
  retryReset = async () => {
    if (this.#state.kind === 'ready' && this.#state.reset.kind === 'error' && this.#state.reset.action === 'retry' && this.#receipt) {
      await this.#postReset()
    }
  }
  async #postReset() {
    const receipt = this.#receipt!
    const generation = ++this.#generation
    this.#reset({ kind: 'posting' })
    try {
      const response = await this.#api.progress.reset('reset_all_progress', receipt.id, receipt.generation)
      if (generation !== this.#generation) return
      receipt.acknowledged = response.progress_generation
      await this.#finishReset(generation)
    } catch (error) {
      this.#authentication(error, generation)
      if (generation !== this.#generation) return
      if (error instanceof ApiError && (error.code === 'progress_reset' || error.code === 'reset_request_conflict')) {
        this.#reset({ kind: 'error', message: text.resetChanged, action: 'reload', open: true })
      } else if (!(error instanceof ApiError) || error.kind === 'network' || error.kind === 'protocol') {
        receipt.uncertain = true
        this.#reset({ kind: 'error', message: text.resetUncertain, action: 'check', open: true })
      } else {
        const message = error.status === 400 ? text.resetInvalid : error.status === 403 ? text.resetForbidden : text.resetFailed
        this.#reset({ kind: 'error', message, action: 'retry', open: true })
      }
    }
  }
  async #finishReset(generation: number) {
    this.#reset({ kind: 'refreshing' })
    try {
      const view = await this.#readView(generation)
      if (generation !== this.#generation) return
      if (BigInt(view.generation) < BigInt(this.#receipt!.acknowledged!)) throw new Error('Stale completion response')
      this.#receipt = undefined
      this.#publish({ kind: 'ready', view, reset: { kind: 'success' } })
    } catch (error) {
      this.#authentication(error, generation)
      if (generation === this.#generation) this.#reset({ kind: 'error', message: text.resetRefreshFailed, action: 'refresh', open: true })
    }
  }
  recoverReset = async () => {
    if (this.#state.kind !== 'ready' || this.#state.reset.kind !== 'error' || !this.#receipt) return
    const action = this.#state.reset.action
    if (action === 'retry') return
    const generation = ++this.#generation
    if (action === 'refresh') { await this.#finishReset(generation); return }
    this.#reset({ kind: 'refreshing' })
    try {
      if (action === 'check') {
        // GET cannot identify this UUID's receipt: allow only an explicit identical POST.
        await this.#api.progress.completion()
        if (generation === this.#generation) this.#reset({ kind: 'error', message: text.resetChecked, action: 'retry', open: true })
      } else {
        const view = await this.#readView(generation)
        if (generation !== this.#generation) return
        this.#receipt = undefined
        this.#publish({ kind: 'ready', view, reset: { kind: 'idle' }, notice: text.resetReloaded })
      }
    } catch (error) {
      this.#authentication(error, generation)
      if (generation === this.#generation) this.#reset({ kind: 'error', message: text.resetCheckFailed, action, open: true })
    }
  }
}
