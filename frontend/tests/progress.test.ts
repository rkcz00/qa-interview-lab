import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createApiClient } from '../src/api/client.ts'
import type { CompletionProgress, TopicSummary } from '../src/api/types.ts'
import { resolveRoute } from '../src/auth/routing.ts'
import { authDestination } from '../src/learning/routing.ts'
import { progressView, ProgressStore } from '../src/progress/model.ts'
import { progressRu as text } from '../src/progress/texts.ts'
import { catalog, completion, deferred, failure, fixture, ready, tick, zero } from './progress-fixture.ts'

test('login always returns to the protected home catalog', () => {
  assert.equal(resolveRoute('/progress'), '/progress')
  assert.equal(authDestination('/progress'), '/')
})

test('empty server catalog is displayed without browser percentage arithmetic', () => {
  assert.deepEqual(progressView(catalog, { progress_generation: '1', overall_completion_progress: 0, topics: [] }),
    { topics: [], navigationTopics: [], total: 0, mastered: 0, percentage: 0, generation: '1' })
})

for (const [name, row] of [
  ['30/70 read-only', { ...completion.topics[1], article_read_at: completion.topics[0].article_read_at, completion_progress: 30 }],
  ['30/70 passed without Read', { ...completion.topics[0], article_read_at: null, completion_progress: 70, mastered: false }],
  ['30/35/35 test passed', { ...completion.topics[0], practice: { task_id: '7', status: 'unattempted' as const }, completion_progress: 65 }],
  ['30/35/35 failed practice retains mastery', { ...completion.topics[0], practice: { task_id: '7', status: 'failed' as const }, completion_progress: 65 }],
  ['30/35/35 practice passed without mastery', { ...completion.topics[0], test: { status: 'failed' as const,
    best_result: { correct_count: 1, total_count: 2, percentage: 50 } }, practice: { task_id: '7', status: 'passed' as const },
    completion_progress: 65, mastered: false }],
  ['M=0 defensive server result', { ...completion.topics[1], article_read_at: completion.topics[0].article_read_at, completion_progress: 30 }],
] as const) {
  test('server projection: ' + name, () => {
    const value: CompletionProgress = { progress_generation: '1', overall_completion_progress: row.completion_progress, topics: [row] }
    const view = progressView(catalog, value)
    assert.equal(view.percentage, row.completion_progress)
    assert.deepEqual(view.topics[0], { ...row, title: catalog.find(topic => topic.topic_id === row.topic_id)!.title })
    assert.equal(view.mastered, row.mastered ? 1 : 0)
  })
}

test('overall and per-topic percentages are copied from JSON, never averaged or derived from mastery', () => {
  const view = progressView(catalog, { ...completion, overall_completion_progress: 91.23 })
  assert.equal(view.percentage, 91.23)
  assert.equal(view.topics[0].completion_progress, 100)
  assert.equal(view.mastered, 1)
})

test('Published snapshot controls membership and numeric ID order; catalog only provides names', () => {
  const view = progressView([...catalog].reverse().concat({ topic_id: '99', title: 'Newer publication' }), completion)
  assert.deepEqual(view.topics.map(topic => topic.topic_id), ['2', '10'])
  assert.deepEqual(view.navigationTopics.map(topic => topic.topic_id), ['10', '2'], 'Sidebar retains the catalog API order')
  assert.equal(view.total, 2)
  const missingTitle = progressView([], completion)
  assert.equal(missingTitle.topics[0].title, text.untitled('2'))
  assert.equal(missingTitle.percentage, completion.overall_completion_progress)
})

test('projection whitelists public fields and contains aggregates rather than attempt IDs/history', () => {
  const extra = { ...completion, internal: 'private', topics: [{ ...completion.topics[0], internal: 'private' }] }
  const view = progressView(catalog, extra)
  assert.equal(JSON.stringify(view).includes('private'), false)
  assert.deepEqual(Object.keys(view.topics[0]).sort(), ['article_read_at', 'completion_progress', 'mastered', 'practice', 'test', 'title', 'topic_id'])
  assert.deepEqual(Object.keys(view.topics[0].test.best_result!).sort(), ['correct_count', 'percentage', 'total_count'])
})

test('store loads catalog and new completion GET only, preserving the strict old Progress API', async () => {
  const { api, calls } = fixture()
  const store = new ProgressStore(api)
  await store.load()
  assert.deepEqual(calls, ['catalog', 'completion'])
  assert.deepEqual(store.getSnapshot(), { kind: 'ready', view: progressView(catalog, completion), reset: { kind: 'idle' } })
})

for (const [status, code, message] of [[404, 'not_found', text.notFound], [403, 'permission_denied', text.forbidden],
  [0, 'network_error', text.network], [500, 'internal_error', text.server]] as const) {
  test(`progress failure ${status}/${code} is explicit and sanitized`, async () => {
    const { api } = fixture()
    const store = new ProgressStore(api)
    await store.load()
    api.progress.completion = async () => { throw failure(status, code) }
    await store.load()
    assert.deepEqual(store.getSnapshot(), { kind: 'error', message })
    assert.equal(JSON.stringify(store.getSnapshot()).includes('Private'), false)
  })
}

test('transport timeout never invents zero progress', async () => {
  const api = createApiClient({ origin: 'http://localhost', baseUrl: '/api/v1/',
    fetch: async () => { throw new DOMException('Private details', 'TimeoutError') } })
  const store = new ProgressStore(api)
  await store.load()
  assert.deepEqual(store.getSnapshot(), { kind: 'error', message: text.network })
})

test('catalog failure does not present a false empty catalog', async () => {
  const { api } = fixture()
  api.learning.catalog = async () => { throw failure(0, 'network_error') }
  const store = new ProgressStore(api)
  await store.load()
  assert.equal(store.getSnapshot().kind, 'error')
})

test('passive autosave refresh preserves focused menu DOM until confirmed data arrives', async () => {
  const { api } = fixture()
  const store = new ProgressStore(api)
  await store.load()
  const before = store.getSnapshot()
  const pending = deferred<CompletionProgress>()
  api.progress.completion = () => pending.promise
  const loading = store.load(true)
  assert.equal(store.getSnapshot(), before)
  pending.resolve(zero('1'))
  await loading
  assert.equal(ready(store).view.percentage, 0)
})

test('authentication failure clears private data despite a pending catalog', async () => {
  const { api } = fixture()
  const pending = deferred<TopicSummary[]>()
  api.learning.catalog = () => pending.promise
  api.progress.completion = async () => { throw failure(403, 'authentication_required') }
  const store = new ProgressStore(api)
  const loading = store.load()
  await tick()
  assert.deepEqual(store.getSnapshot(), { kind: 'authentication' })
  pending.resolve(catalog)
  await loading
  assert.deepEqual(store.getSnapshot(), { kind: 'authentication' })
})

test('late authentication failure overrides an earlier network failure', async () => {
  const { api } = fixture()
  const pending = deferred<CompletionProgress>()
  api.learning.catalog = async () => { throw failure(0, 'network_error') }
  api.progress.completion = () => pending.promise
  const store = new ProgressStore(api)
  await store.load()
  pending.reject(failure(403, 'authentication_required'))
  await tick()
  assert.deepEqual(store.getSnapshot(), { kind: 'authentication' })
})

test('unmount and superseded loads ignore late private data and expired sessions', async () => {
  const { api } = fixture()
  const pending = deferred<CompletionProgress>()
  api.progress.completion = () => pending.promise
  const store = new ProgressStore(api)
  const loading = store.load()
  store.invalidate()
  pending.resolve(completion)
  await loading
  assert.deepEqual(store.getSnapshot(), { kind: 'loading' })
  const late = deferred<CompletionProgress>()
  api.progress.completion = () => late.promise
  const old = store.load()
  api.progress.completion = async () => zero()
  await store.load()
  const latest = store.getSnapshot()
  late.reject(failure(403, 'authentication_required'))
  await old
  assert.equal(store.getSnapshot(), latest)
})
