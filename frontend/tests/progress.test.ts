import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ApiError, createApiClient } from '../src/api/client.ts'
import type { Progress, TopicSummary } from '../src/api/types.ts'
import { resolveRoute } from '../src/auth/routing.ts'
import { authDestination } from '../src/learning/routing.ts'
import { progressView, ProgressStore } from '../src/progress/model.ts'
import { progressRu as text } from '../src/progress/texts.ts'

const catalog: TopicSummary[] = [{ topic_id: '2', title: 'Тестирование' }, { topic_id: '10', title: 'Автоматизация' }]
const progress: Progress = { topic_id: '2', article_read_at: '2026-11-12T10:00:00Z', mastered: true,
  best_result: { correct_count: 4, total_count: 5, percentage: 80 } }
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
    learning: { catalog: async (_language?: 'ru' | 'en'): Promise<TopicSummary[]> => { calls.push('catalog'); return catalog } },
    progress: { current: async (): Promise<Progress[]> => { calls.push('progress'); return [progress] } },
    assessment: { history: async () => { throw new Error('UI must not request history') } },
  } }
}
test('login always returns to the protected home catalog', () => {
  assert.equal(resolveRoute('/progress'), '/progress')
  assert.equal(authDestination('/progress'), '/')
  assert.equal(authDestination(), '/')
})
test('empty catalog has zero progress without division by zero', () => {
  assert.deepEqual(progressView([], [progress]), { topics: [], total: 0, mastered: 0, percentage: 0 })
})
test('overall progress counts server mastery only within Published catalog', () => {
  const view = progressView(catalog, [progress, { ...progress, topic_id: '99' }])
  assert.equal(view.total, 2)
  assert.equal(view.mastered, 1)
  assert.equal(view.percentage, 50)
})
test('unread, read-only and completed-but-not-mastered never increase the percentage', () => {
  for (const readAt of [null, progress.article_read_at]) {
    const view = progressView(catalog, [{ ...progress, article_read_at: readAt, mastered: false,
      best_result: { correct_count: 15999, total_count: 20000, percentage: 80 } }])
    assert.equal(view.mastered, 0)
    assert.equal(view.percentage, 0)
  }
})
test('all mastered and partially mastered totals have stable display percentages', () => {
  assert.equal(progressView(catalog, catalog.map(t => ({ ...progress, topic_id: t.topic_id }))).percentage, 100)
  assert.equal(progressView([...catalog, { topic_id: '11', title: 'API' }], [progress]).percentage, 33.33)
})
test('duplicate catalog and progress rows cannot double-count mastery', () => {
  const view = progressView([...catalog, catalog[0]], [progress, progress])
  assert.equal(view.total, 2)
  assert.equal(view.mastered, 1)
  assert.deepEqual(view.topics.map(t => t.topic_id), ['2', '10'])
})
test('progress projection exposes no result, attempts, history or private fields', () => {
  const extraTopic = { ...catalog[0], internal: 'private' }
  const extraProgress = { ...progress, internal: 'private' }
  const view = progressView([extraTopic], [extraProgress])
  assert.deepEqual(Object.keys(view).sort(), ['mastered', 'percentage', 'topics', 'total'])
  assert.deepEqual(Object.keys(view.topics[0]).sort(), ['title', 'topic_id'])
  assert.equal(JSON.stringify(view).includes('private'), false)
})
test('store uses only the existing catalog and progress GETs', async () => {
  const { api, calls } = mockApi()
  const store = new ProgressStore(api)
  await store.load()
  assert.deepEqual(calls, ['catalog', 'progress'])
  assert.deepEqual(store.getSnapshot(), { kind: 'ready', view: progressView(catalog, [progress]) })
})
for (const [status, code, message] of [[404, 'not_found', text.notFound], [403, 'permission_denied', text.forbidden],
  [0, 'network_error', text.network], [500, 'internal_error', text.server]] as const) {
  test(`progress failure ${status}/${code} is explicit and sanitized`, async () => {
    const { api } = mockApi()
    const store = new ProgressStore(api)
    await store.load()
    api.progress.current = async () => { throw failure(status, code) }
    await store.load()
    assert.deepEqual(store.getSnapshot(), { kind: 'error', message })
    assert.equal(JSON.stringify(store.getSnapshot()).includes('Private internal details'), false)
  })
}
test('transport timeout is normalized without inventing zero progress', async () => {
  const api = createApiClient({ origin: 'http://localhost', baseUrl: '/api/v1/',
    fetch: async () => { throw new DOMException('Private details', 'TimeoutError') } })
  const store = new ProgressStore(api)
  await store.load()
  assert.deepEqual(store.getSnapshot(), { kind: 'error', message: text.network })
})
test('catalog failure does not present a false empty catalog', async () => {
  const { api } = mockApi()
  api.learning.catalog = async () => { throw failure(0, 'network_error') }
  const store = new ProgressStore(api)
  await store.load()
  assert.equal(store.getSnapshot().kind, 'error')
})
test('foreground retry clears old values; passive autosave refresh preserves focused menu DOM', async () => {
  const { api } = mockApi()
  const store = new ProgressStore(api)
  await store.load()
  const ready = store.getSnapshot()
  const pending = deferred<Progress[]>()
  api.progress.current = () => pending.promise
  const loading = store.load(true)
  assert.equal(store.getSnapshot(), ready)
  pending.resolve([])
  await loading
  const next = deferred<Progress[]>()
  api.progress.current = () => next.promise
  const foreground = store.load()
  assert.deepEqual(store.getSnapshot(), { kind: 'loading' })
  next.resolve([progress])
  await foreground
  assert.equal(store.getSnapshot().kind, 'ready')
})
test('authentication failure clears private progress despite a pending catalog', async () => {
  const { api } = mockApi()
  const pending = deferred<TopicSummary[]>()
  api.learning.catalog = () => pending.promise
  api.progress.current = async () => { throw failure(403, 'authentication_required') }
  const store = new ProgressStore(api)
  const loading = store.load()
  await tick()
  assert.deepEqual(store.getSnapshot(), { kind: 'authentication' })
  pending.resolve(catalog)
  await loading
  assert.deepEqual(store.getSnapshot(), { kind: 'authentication' })
})
test('late authentication failure overrides an earlier network failure', async () => {
  const { api } = mockApi()
  const pending = deferred<Progress[]>()
  api.learning.catalog = async () => { throw failure(0, 'network_error') }
  api.progress.current = () => pending.promise
  const store = new ProgressStore(api)
  await store.load()
  pending.reject(failure(403, 'authentication_required'))
  await tick()
  assert.deepEqual(store.getSnapshot(), { kind: 'authentication' })
})
test('unmount and superseded loads ignore late private data and expired sessions', async () => {
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
