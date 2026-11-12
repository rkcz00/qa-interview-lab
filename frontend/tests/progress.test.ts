import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ApiError, createApiClient } from '../src/api/client.ts'
import type { Progress, SubmittedAttempt, TopicSummary } from '../src/api/types.ts'
import type { Destination } from '../src/auth/routing.ts'
import { resolveRoute } from '../src/auth/routing.ts'
import { authDestination } from '../src/learning/routing.ts'
import { attemptDate, progressView, ProgressStore } from '../src/progress/model.ts'
import { progressRu as text } from '../src/progress/texts.ts'

const result = { correct_count: 4, total_count: 5, percentage: 80 }
const catalog: TopicSummary[] = [{ topic_id: '2', title: 'Тестирование' }, { topic_id: '10', title: 'Автоматизация' }]
const progress: Progress = { topic_id: '2', article_read_at: '2026-11-12T10:00:00Z', mastered: true, best_result: result }
const attempt: SubmittedAttempt = { attempt_id: '42', topic_id: '2', topic_title: 'Testing', status: 'submitted',
  submitted_at: '2026-11-12T11:00:00Z', submitted_language: 'en', result }
const failure = (status: number, code: string) => new ApiError({ status, code, kind: status ? 'http' : 'network', message: 'Private internal details' })
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const tick = async () => { await new Promise<void>(resolve => setTimeout(resolve, 0)) }
function mockApi() {
  const calls: string[] = []
  return { calls, api: {
    learning: { catalog: async (language?: 'ru' | 'en'): Promise<TopicSummary[]> => { calls.push('catalog:' + language); return catalog } },
    progress: { current: async (): Promise<Progress[]> => { calls.push('progress'); return [progress] } },
    assessment: { history: async (): Promise<SubmittedAttempt[]> => { calls.push('history'); return [attempt] } },
  } }
}

test('progress is a protected internal route without arbitrary login redirects', () => {
  assert.equal(resolveRoute('/progress'), '/progress')
  assert.equal(authDestination('/progress'), '/progress')
  for (const path of ['/progress/', '/progress/2', '/progress?language=en', '//outside.invalid/progress']) assert.equal(resolveRoute(path), null)
  for (const path of ['https://outside.invalid/progress', '/progress?next=/session', '//outside.invalid']) {
    assert.equal(authDestination(path as Destination), '/session')
  }
})

test('empty data and untouched Published topics remain distinct successful states', () => {
  assert.deepEqual(progressView([], [], []), { topics: [], history: [], hasSavedProgress: false })
  const view = progressView(catalog, [], [])
  assert.equal(view.hasSavedProgress, false)
  assert.deepEqual(view.topics.map(row => row.topicId), ['2', '10'])
  for (const row of view.topics) {
    assert.equal(row.available, true)
    assert.deepEqual(row.progress, { readAt: null, mastered: false, bestResult: null })
  }
})

test('server mastery and best result are used without client recalculation', () => {
  const state = { ...progress, mastered: false, best_result: { correct_count: 15999, total_count: 20000, percentage: 80 } }
  const view = progressView(catalog, [state], [{ ...attempt, result: { correct_count: 5, total_count: 5, percentage: 100 } }])
  assert.deepEqual(view.topics[0]?.progress, { readAt: state.article_read_at, mastered: false, bestResult: state.best_result })
})

test('RU and EN attempts share one progress row while preserving separate history and order', () => {
  const ru = { ...attempt, attempt_id: '41', topic_title: 'Тестирование раньше', submitted_language: 'ru' as const }
  const view = progressView(catalog, [progress], [attempt, ru])
  assert.equal(view.topics.filter(row => row.topicId === '2').length, 1)
  assert.equal(view.topics[0]?.title, 'Тестирование')
  assert.deepEqual(view.history.map(row => [row.attemptId, row.language, row.title]), [['42', 'en', 'Testing'], ['41', 'ru', 'Тестирование раньше']])
})

test('unavailable saved topics use history titles or an explicit ID without inventing availability', () => {
  const readOnly = { ...progress, topic_id: '9', best_result: null, mastered: false }
  const view = progressView([], [progress, readOnly], [attempt])
  assert.deepEqual(view.topics.map(row => [row.topicId, row.available, row.titleSource]), [['2', false, 'history'], ['9', false, 'unavailable']])
  assert.equal(view.topics[0]?.title, 'Testing')
  assert.equal(view.topics[0]?.titleLanguage, 'en')
  assert.equal(view.topics[1]?.title, 'Тема № 9')
  assert.equal(view.topics[0]?.progress?.mastered, true)
})

test('history received without a matching progress row remains unknown during concurrent updates', () => {
  const view = progressView(catalog, [], [attempt])
  assert.equal(view.topics[0]?.progress, null)
  assert.equal(view.topics[1]?.progress?.mastered, false)
  assert.equal(view.hasSavedProgress, true)
})

test('public projections copy only allowed result and history fields', () => {
  const extra = { ...attempt, snapshot: 'internal', server_key: 'internal', result: { ...result, correct_choices: ['internal'] } }
  const view = progressView([], [progress], [extra])
  assert.deepEqual(Object.keys(view.history[0]!.result).sort(), ['correct_count', 'percentage', 'total_count'])
  assert.equal(/snapshot|server_key|correct_choices|submitted_answers/u.test(JSON.stringify(view)), false)
  assert.notEqual(view.history[0]?.result, extra.result)
})

test('dates expose canonical machine time and safe browser-local display', () => {
  const date = attemptDate(attempt.submitted_at)
  assert.equal(date.iso, '2026-11-12T11:00:00.000Z')
  assert.equal(date.text, new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(attempt.submitted_at)))
  assert.deepEqual(attemptDate('invalid date'), { text: text.invalidDate })
})

test('store loads exactly the existing read-only contracts with RU catalog titles', async () => {
  const { api, calls } = mockApi()
  const store = new ProgressStore(api)
  await store.load()
  assert.deepEqual(calls, ['catalog:ru', 'progress', 'history'])
  assert.deepEqual(store.getSnapshot(), { kind: 'ready', view: progressView(catalog, [progress], [attempt]) })
})

for (const [status, code, message] of [[404, 'not_found', text.notFound], [403, 'permission_denied', text.forbidden],
  [0, 'network_error', text.network], [500, 'internal_error', text.server]] as const) {
  test(`progress failure ${status}/${code} is explicit and does not show a false empty state`, async () => {
    const { api } = mockApi()
    const store = new ProgressStore(api)
    await store.load()
    api.assessment.history = async () => { throw failure(status, code) }
    await store.load()
    assert.deepEqual(store.getSnapshot(), { kind: 'error', message })
    assert.equal(JSON.stringify(store.getSnapshot()).includes('Private internal details'), false)
  })
}

test('the existing API client normalizes a transport timeout into a safe progress error', async () => {
  const api = createApiClient({ origin: 'http://localhost', baseUrl: '/api/v1/',
    fetch: async () => { throw new DOMException('Private transport details', 'TimeoutError') } })
  const store = new ProgressStore(api)
  await store.load()
  assert.deepEqual(store.getSnapshot(), { kind: 'error', message: text.network })
})

test('catalog failure never mislabels saved topics as unavailable', async () => {
  const { api } = mockApi()
  api.learning.catalog = async () => { throw failure(0, 'network_error') }
  const store = new ProgressStore(api)
  await store.load()
  assert.equal(store.getSnapshot().kind, 'error')
})

test('refresh clears old private rows and retry restores successful data', async () => {
  const { api } = mockApi()
  const store = new ProgressStore(api)
  await store.load()
  const pending = deferred<Progress[]>()
  api.progress.current = () => pending.promise
  const loading = store.load()
  assert.deepEqual(store.getSnapshot(), { kind: 'loading' })
  pending.resolve([])
  await loading
  assert.equal(store.getSnapshot().kind, 'ready')
})

test('authentication failure overrides pending responses and clears private data', async () => {
  const { api } = mockApi()
  const store = new ProgressStore(api)
  await store.load()
  const pending = deferred<SubmittedAttempt[]>()
  api.progress.current = async () => { throw failure(403, 'authentication_required') }
  api.assessment.history = () => pending.promise
  const loading = store.load()
  await tick()
  assert.deepEqual(store.getSnapshot(), { kind: 'authentication' })
  pending.resolve([attempt])
  await loading
  assert.deepEqual(store.getSnapshot(), { kind: 'authentication' })
})

test('late authentication failure overrides an earlier network failure', async () => {
  const { api } = mockApi()
  const pending = deferred<SubmittedAttempt[]>()
  api.learning.catalog = async () => { throw failure(0, 'network_error') }
  api.assessment.history = () => pending.promise
  const store = new ProgressStore(api)
  await store.load()
  assert.equal(store.getSnapshot().kind, 'error')
  pending.reject(failure(403, 'authentication_required'))
  await tick()
  assert.deepEqual(store.getSnapshot(), { kind: 'authentication' })
})

test('unmount and superseded loads cannot publish stale data or late authentication', async () => {
  const { api } = mockApi()
  const pending = deferred<Progress[]>()
  api.progress.current = () => pending.promise
  const store = new ProgressStore(api)
  const loading = store.load()
  store.invalidate()
  pending.resolve([progress])
  await loading
  assert.deepEqual(store.getSnapshot(), { kind: 'loading' })
  const late = deferred<Progress[]>()
  api.progress.current = () => late.promise
  const old = store.load()
  api.progress.current = async () => []
  await store.load()
  const latest = store.getSnapshot()
  late.reject(failure(403, 'authentication_required'))
  await old
  assert.equal(store.getSnapshot(), latest)
})
