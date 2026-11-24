import assert from 'node:assert/strict'
import { ApiError } from '../src/api/client.ts'
import type { CompletionProgress, TopicSummary } from '../src/api/types.ts'
import type { ProgressStore } from '../src/progress/model.ts'

export const catalog: TopicSummary[] = [{ topic_id: '2', title: 'Тестирование' }, { topic_id: '10', title: 'Автоматизация' }]
export const completion: CompletionProgress = { progress_generation: '1', overall_completion_progress: 50, topics: [{
  topic_id: '2', article_read_at: '2026-11-23T10:00:00Z', mastered: true, completion_progress: 100,
  test: { status: 'passed', best_result: { correct_count: 4, total_count: 5, percentage: 80 } }, practice: null,
}, { topic_id: '10', article_read_at: null, mastered: false, completion_progress: 0,
  test: { status: 'unattempted', best_result: null }, practice: null,
}] }
export const uuid = '00000000-0000-4000-8000-000000000035'
export function zero(generation = '2'): CompletionProgress {
  return { progress_generation: generation, overall_completion_progress: 0, topics: completion.topics.map(topic => ({
    ...topic, article_read_at: null, mastered: false, completion_progress: 0, test: { status: 'unattempted', best_result: null },
  })) }
}
export function failure(status: number, code: string, kind: 'http' | 'network' | 'protocol' = status ? 'http' : 'network') {
  return new ApiError({ status, code, kind, message: 'Private internal details' })
}
export function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
export const tick = async () => { await new Promise<void>(resolve => setTimeout(resolve, 0)) }
export function fixture() {
  const calls: string[] = []
  const posts: unknown[][] = []
  const api = {
    learning: { catalog: async (_language?: 'ru' | 'en') => { calls.push('catalog'); return structuredClone(catalog) } },
    progress: {
      completion: async (): Promise<CompletionProgress> => { calls.push('completion'); return structuredClone(completion) },
      reset: async (...args: ['reset_all_progress', string, string]) => {
        calls.push('reset'); posts.push(args); return { progress_generation: '2' }
      },
    },
    assessment: { history: async () => { throw new Error('UI must not request history') } },
  }
  return { api, calls, posts }
}
export function ready(store: ProgressStore) {
  const state = store.getSnapshot()
  if (state.kind !== 'ready') assert.fail('Expected ready progress')
  return state
}
