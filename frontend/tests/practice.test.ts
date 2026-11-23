import assert from 'node:assert/strict'
import test from 'node:test'
import type { TestContext } from 'node:test'
import { ApiError, createApiClient } from '../src/api/client.ts'
import type { ApiClient } from '../src/api/client.ts'
import type { PendingPractice, PracticePreview, SubmittedPractice } from '../src/api/types.ts'
import * as decode from '../src/api/decoders.ts'
import { PreviewStore, SubmissionStore, answerError, answerLength } from '../src/practice/model.ts'
import { practiceDestination, practiceLocation } from '../src/practice/routing.ts'
import { resolveRoute } from '../src/auth/routing.ts'
import { allowHistoryNavigation, learnerNavigation } from '../src/ui/navigation.ts'
import { protectPracticeHistory } from '../src/practice/useUnsavedPractice.ts'

const preview: PracticePreview = { topic_id: '1', task_id: '2', practice_kind: 'single_correct_answer', language: 'ru', title: 'Задание',
  can_start: true, blocked_by: [], normalization_mode: 'lf_trim_outer_v1', answer_max_length: 5000 }
const pending: PendingPractice = { submission_id: '3', topic_id: '1', task_id: '2', status: 'in_progress', language: 'ru', task: {
  practice_kind: 'single_correct_answer', source_type: 'python', title: 'Задание', prompt: 'Определите вывод.',
  source_text: 'print(1 + 1)', input_data: '', environment: 'Python 3.14.2', output_spec: 'stdout', normalization_mode: 'lf_trim_outer_v1', answer_max_length: 5000,
} }
const submitted: SubmittedPractice = { submission_id: '3', topic_id: '1', task_id: '2', task_title: 'Задание', status: 'submitted',
  submitted_language: 'ru', submitted_at: '2026-11-19T00:00:00Z', result: { verdict: 'correct' } }
function error(status: number, code: string) { return new ApiError({ status, code, kind: status ? 'http' : 'network', message: 'safe' }) }
function deferred<T>() { let resolve!: (value: T) => void; let reject!: (reason: unknown) => void; const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }
function fixture() {
  const calls: { method: string; args: unknown[] }[] = []
  const api: ApiClient['practice'] = {
    preview: async (...args) => { calls.push({ method: 'preview', args }); return { ...preview, language: args[1] ?? 'ru' } },
    start: async (...args) => { calls.push({ method: 'start', args }); return { ...pending, language: args[1] } },
    get: async (...args) => { calls.push({ method: 'get', args }); return { ...pending, language: args[1] ?? 'ru' } },
    submit: async (...args) => { calls.push({ method: 'submit', args }); return { ...submitted, submitted_language: args[1] } },
    delete: async (...args) => { calls.push({ method: 'delete', args }) },
  }
  return { api, calls }
}

function navigationWindow(t: TestContext, pathname: string) {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'window')
  const pushes: string[] = []
  const location = { pathname }
  const browser = Object.assign(new EventTarget(), { location, history: {
    pushState(_data: unknown, _unused: string, url?: string | URL | null) {
      pushes.push(String(url))
      location.pathname = new URL(String(url), 'https://qil.example').pathname
    },
  } })
  Object.defineProperty(globalThis, 'window', { configurable: true, value: browser })
  t.after(() => { if (descriptor) Object.defineProperty(globalThis, 'window', descriptor); else Reflect.deleteProperty(globalThis, 'window') })
  return { location, pushes }
}

test('cancelled history navigation restores the work URL before the router may unmount it', t => {
  const { pushes } = navigationWindow(t, '/topics/1/practice')
  let confirmations = 0
  const release = protectPracticeHistory('/practice-submissions/3?language=en', () => { confirmations++; return false })
  try {
    assert.equal(allowHistoryNavigation(), false)
    assert.equal(confirmations, 1)
    assert.deepEqual(pushes, ['/practice-submissions/3?language=en'])
  } finally { release() }
  assert.equal(allowHistoryNavigation(), true)
  assert.equal(confirmations, 1)
})

test('history language changes and confirmed leave proceed; cleanup releases the guard', t => {
  const { location, pushes } = navigationWindow(t, '/practice-submissions/3')
  let confirmations = 0
  const release = protectPracticeHistory('/practice-submissions/3?language=en', () => { confirmations++; return true })
  try {
    assert.equal(allowHistoryNavigation(), true)
    assert.equal(confirmations, 0)
    location.pathname = '/topics/1'
    assert.equal(allowHistoryNavigation(), true)
    assert.equal(confirmations, 1)
    assert.deepEqual(pushes, [])
  } finally { release() }
  assert.equal(allowHistoryNavigation(), true)
  assert.equal(confirmations, 1)
})
test('routes are same-origin internal paths with independent ru/en; malformed paths and queries are rejected', () => {
  for (const kind of ['preview', 'submission'] as const) for (const language of ['ru', 'en'] as const) {
    const destination = practiceDestination({ kind, id: '3', language })
    const [path, query = ''] = destination.split('?')
    const route = resolveRoute(path)!
    assert.deepEqual(practiceLocation(route, query), { kind, id: '3', language })
    assert.equal(learnerNavigation(path)[0].current, 'location')
    for (const bad of ['language=', 'language=de', 'language=ru&language=en', 'next=https://example.invalid']) assert.equal(practiceLocation(route, bad), null)
  }
  for (const bad of ['/practice-submissions/%2fexternal', '/practice-submissions/%2e%2e', '/practice-submissions/%00', '/practice-submissions/%xy']) assert.equal(practiceLocation(resolveRoute(bad)!, ''), null)
})
test('answer validation counts code points, preserves empty input and significant characters', () => {
  assert.equal(answerLength('😀'.repeat(5000)), 5000)
  assert.equal(answerError('😀'.repeat(5000)), null)
  assert.ok(answerError('😀'.repeat(5001)))
  assert.equal(answerError(''), null)
  assert.equal(answerError(' \t\n'), null)
  assert.ok(answerError('\0'))
  assert.ok(answerError('\ud800'))
})
for (const language of ['ru', 'en'] as const) test(`API routes, exact body, credentials and CSRF: ${language}`, async () => {
  const routes = [
    { path: `topics/1/practice/?language=${language}`, body: undefined, value: { ...preview, language }, status: 200, invoke: (api: ApiClient) => api.practice.preview('1', language) },
    { path: 'topics/1/practice/submissions/', body: { language }, value: { ...pending, language }, status: 201, invoke: (api: ApiClient) => api.practice.start('1', language) },
    { path: `practice-submissions/3/?language=${language}`, body: undefined, value: { ...pending, language }, status: 200, invoke: (api: ApiClient) => api.practice.get('3', language) },
    { path: 'practice-submissions/3/submit/', body: { language, answer_text: ' \n' }, value: { ...submitted, submitted_language: language }, status: 200, invoke: (api: ApiClient) => api.practice.submit('3', language, ' \n') },
    { path: 'practice-submissions/3/delete/', body: {}, value: undefined, status: 204, invoke: (api: ApiClient) => api.practice.delete('3') },
  ]
  for (const route of routes) {
    const calls: { url: string; init: RequestInit }[] = []
    const api = createApiClient({ origin: 'http://localhost', baseUrl: '/api/v1/', fetch: async (input, init) => {
      calls.push({ url: String(input), init: init! })
      if (String(input).endsWith('/completion-progress/')) return Response.json({ data: {
        progress_generation: '1', overall_completion_progress: 0, topics: [],
      } })
      return String(input).endsWith('/csrf/') ? Response.json({ data: { csrf_token: 'synthetic-test-token' } }) : route.status === 204 ? new Response(null, { status: 204 }) : Response.json({ data: route.value }, { status: route.status })
    } })
    await route.invoke(api)
    const call = calls.at(-1)!
    assert.equal(call.url, 'http://localhost/api/v1/' + route.path)
    assert.equal(call.init.method, route.body === undefined ? 'GET' : 'POST')
    assert.equal(call.init.credentials, 'include')
    assert.equal(calls.length, route.body === undefined ? 1 : 3)
    if (route.body !== undefined) {
      assert.ok(new Headers(call.init.headers).get('X-CSRFToken'))
      assert.equal(new Headers(call.init.headers).get('X-Progress-Generation'), '1')
      assert.deepEqual(JSON.parse(String(call.init.body)), route.body)
    }
  }
})
for (const [status, code] of [[400, 'validation_error'], [403, 'csrf_failed'], [404, 'not_found'], [409, 'practice_already_submitted']] as const) test(`ApiError preserves Practice ${status}`, async () => {
  let posts = 0
  const api = createApiClient({ origin: 'http://localhost', baseUrl: '/api/v1/', fetch: async (input, init) => {
    if (String(input).endsWith('/completion-progress/')) return Response.json({ data: {
      progress_generation: '1', overall_completion_progress: 0, topics: [],
    } })
    if (String(input).endsWith('/csrf/')) return Response.json({ data: { csrf_token: 'synthetic-test-token' } })
    if (init?.method === 'POST') posts++
    return Response.json({ error: { code, message: 'Safe error', ...(status === 400 ? { fields: { answer_text: ['Invalid'] } } : {}) } }, { status })
  } })
  await assert.rejects(api.practice.submit('3', 'ru', ''), e => e instanceof ApiError && e.status === status && e.code === code)
  assert.equal(posts, 1)
})
test('decoders reject private and unexpected fields at every practice level', () => {
  for (const name of ['expected_answer', 'task_snapshot', 'source_revision', 'submitted_answer', 'server_key', 'user_id']) {
    assert.throws(() => decode.practicePreview({ ...preview, [name]: 'hidden' }))
    assert.throws(() => decode.pendingPractice({ ...pending, [name]: 'hidden' }))
    assert.throws(() => decode.pendingPractice({ ...pending, task: { ...pending.task, [name]: 'hidden' } }))
    assert.throws(() => decode.submittedPractice({ ...submitted, [name]: 'hidden' }))
    assert.throws(() => decode.submittedPractice({ ...submitted, result: { ...submitted.result, [name]: 'hidden' } }))
  }
  assert.throws(() => decode.practicePreview({ ...preview, can_start: false }))
  assert.throws(() => decode.practicePreview({ ...preview, blocked_by: ['test_not_submitted', 'article_not_read'], can_start: false }))
  assert.throws(() => decode.pendingPractice({ ...pending, task: { ...pending.task, answer_max_length: 5001 } }))
  assert.throws(() => decode.submittedPractice({ ...submitted, result: { verdict: 'unknown' } }))
})
test('locked preview cannot start; explicit start sends only once and lost start has no automatic retry', async () => {
  const { api, calls } = fixture()
  api.preview = async () => ({ ...preview, can_start: false, blocked_by: ['article_not_read'] })
  const store = new PreviewStore(api, '1')
  await store.load('ru'); await store.start()
  assert.equal(calls.filter(x => x.method === 'start').length, 0)
  api.preview = async () => preview
  await store.load('ru')
  const hold = deferred<PendingPractice>(); let starts = 0
  api.start = () => { starts++; return hold.promise }
  const first = store.start(); await store.start(); await store.load('en')
  assert.equal(starts, 1)
  hold.reject(error(0, 'network_error')); await first
  await store.load('ru'); await store.start()
  assert.equal(starts, 1); assert.equal(store.getSnapshot().kind, 'uncertain')
})
test('language reload preserves the raw answer, discards stale responses and never POSTs', async () => {
  const { api, calls } = fixture(); const store = new SubmissionStore(api, '3')
  await store.load('ru'); store.setAnswer(' raw\r\n ')
  const older = deferred<PendingPractice>()
  api.get = async (_id, language) => language === 'en' ? older.promise : pending
  const first = store.load('en'); await store.load('ru')
  older.resolve({ ...pending, language: 'en' }); await first
  assert.equal(store.getSnapshot().answer, ' raw\r\n ')
  const item = store.getSnapshot().item
  assert.equal(item?.status === 'in_progress' && item.language, 'ru')
  assert.equal(calls.some(x => x.method === 'submit'), false)
})
test('empty input is submitted explicitly and duplicate clicks send once', async () => {
  const { api } = fixture(); let count = 0
  const hold = deferred<SubmittedPractice>()
  api.submit = (_id, _language, value) => { count++; assert.equal(value, ''); return hold.promise }
  const store = new SubmissionStore(api, '3'); await store.load('ru')
  const first = store.submit(); await store.submit(); await store.load('en')
  assert.equal(count, 1)
  hold.resolve(submitted); await first
  assert.equal(store.getSnapshot().kind, 'result'); assert.equal(store.getSnapshot().answer, '')
  assert.deepEqual(store.getSnapshot().item, submitted)
})
test('timeout checks GET first and only explicit frozen retry can POST again', async () => {
  const { api } = fixture(); const values: string[] = []
  api.submit = async (_id, _language, value) => { values.push(value); if (values.length === 1) throw error(0, 'network_error'); return submitted }
  const store = new SubmissionStore(api, '3'); await store.load('ru'); store.setAnswer(' raw answer ')
  await store.submit(); assert.equal(store.getSnapshot().kind, 'uncertain'); assert.equal(store.getSnapshot().canRetry, true)
  store.setAnswer('changed'); await store.submit()
  assert.equal(values.length, 1)
  await store.retrySame(); assert.deepEqual(values, [' raw answer ', ' raw answer '])
  assert.equal(store.getSnapshot().kind, 'result')
})
test('lost submit response resolved by GET does not repeat POST', async () => {
  const { api } = fixture(); const store = new SubmissionStore(api, '3'); await store.load('ru')
  let writes = 0
  api.submit = async () => { writes++; throw error(0, 'network_error') }
  api.get = async () => submitted
  await store.submit(); assert.equal(store.getSnapshot().kind, 'result'); await store.retrySame(); assert.equal(writes, 1)
})
test('409 loads the saved result and prevents any changed retry', async () => {
  const { api } = fixture(); const store = new SubmissionStore(api, '3'); await store.load('ru')
  let writes = 0
  api.submit = async () => { writes++; throw error(409, 'practice_already_submitted') }; api.get = async () => submitted
  store.setAnswer('changed'); await store.submit(); await store.retrySame()
  assert.equal(store.getSnapshot().kind, 'result'); assert.ok(store.getSnapshot().message); assert.equal(writes, 1)
})
for (const code of ['validation_error', 'csrf_failed']) test(`${code} retains input for explicit correction`, async () => {
  const { api } = fixture(); api.submit = async () => { throw error(code === 'csrf_failed' ? 403 : 400, code) }
  const store = new SubmissionStore(api, '3'); await store.load('ru'); store.setAnswer('typed')
  await store.submit(); assert.equal(store.getSnapshot().kind, 'ready'); assert.equal(store.getSnapshot().answer, 'typed')
})
test('session loss and missing/foreign work clear the draft', async () => {
  for (const failure of [error(403, 'authentication_required'), error(404, 'not_found')]) {
    const { api } = fixture(); const store = new SubmissionStore(api, '3'); await store.load('ru'); store.setAnswer('private input')
    api.get = async () => { throw failure }; await store.load('en')
    assert.equal(store.getSnapshot().answer, ''); assert.equal(store.getSnapshot().item, null)
  }
})
test('delete needs confirmation, is single-flight and redirects only to an available practice', async () => {
  const { api } = fixture(); const store = new SubmissionStore(api, '3'); await store.load('ru')
  let deletes = 0; const hold = deferred<void>(); api.delete = () => { deletes++; return hold.promise }
  await store.remove(false); assert.equal(deletes, 0)
  const first = store.remove(true); await store.remove(true); assert.equal(deletes, 1)
  hold.resolve(); await first; assert.equal(store.getSnapshot().kind, 'deleted'); assert.equal(store.getSnapshot().deletedTopic, '1')
})
test('delete timeout with GET 404 confirms removal without a second POST', async () => {
  const { api } = fixture(); const store = new SubmissionStore(api, '3'); await store.load('ru')
  let deletes = 0; api.delete = async () => { deletes++; throw error(0, 'network_error') }
  api.get = async () => { throw error(404, 'not_found') }; api.preview = async () => { throw error(404, 'not_found') }
  await store.remove(true); assert.equal(store.getSnapshot().kind, 'deleted'); assert.equal(store.getSnapshot().deletedTopic, null); assert.equal(deletes, 1)
})
test('delete timeout with existing work permits only an explicit retry', async () => {
  const { api } = fixture(); const store = new SubmissionStore(api, '3'); await store.load('ru')
  let deletes = 0; api.delete = async () => { deletes++; if (deletes === 1) throw error(0, 'network_error') }
  await store.remove(true); assert.equal(store.getSnapshot().kind, 'delete_uncertain'); assert.equal(store.getSnapshot().canRetry, true)
  assert.equal(deletes, 1); await store.retryDelete(); assert.equal(deletes, 2); assert.equal(store.getSnapshot().kind, 'deleted')
})

test('translation errors and retry preserve the draft without submitting it', async () => {
  const { api, calls } = fixture(); const store = new SubmissionStore(api, '3'); await store.load('ru'); store.setAnswer(' draft ')
  api.get = async () => { throw error(0, 'network_error') }; await store.load('en')
  assert.equal(store.getSnapshot().kind, 'error'); assert.equal(store.getSnapshot().answer, ' draft ')
  api.get = async () => ({ ...pending, language: 'en' }); await store.load('en')
  assert.equal(store.getSnapshot().kind, 'ready'); assert.equal(store.getSnapshot().answer, ' draft ')
  assert.equal(calls.some(call => call.method === 'submit'), false)
})
test('a failed status GET forbids retry until an explicit successful GET', async () => {
  const { api } = fixture(); const store = new SubmissionStore(api, '3'); await store.load('ru'); store.setAnswer('frozen')
  let writes = 0; api.submit = async () => { writes++; if (writes === 1) throw error(0, 'network_error'); return submitted }
  api.get = async () => { throw error(0, 'network_error') }
  await store.submit(); assert.equal(store.getSnapshot().canRetry, false)
  await store.retrySame(); assert.equal(writes, 1)
  api.get = async () => pending; await store.check(); assert.equal(store.getSnapshot().canRetry, true)
  await store.retrySame(); assert.equal(writes, 2)
})
test('a pending status after 409 never allows a second POST', async () => {
  const { api } = fixture(); const store = new SubmissionStore(api, '3'); await store.load('ru')
  let writes = 0; api.submit = async () => { writes++; throw error(409, 'practice_already_submitted') }
  await store.submit(); assert.equal(store.getSnapshot().kind, 'uncertain'); assert.equal(store.getSnapshot().canRetry, false)
  await store.retrySame(); assert.equal(writes, 1)
  api.get = async () => submitted; await store.check(); assert.equal(store.getSnapshot().kind, 'result')
})
test('invalid length cannot submit, and a late response cannot restore disposed user state', async () => {
  const { api, calls } = fixture(); const store = new SubmissionStore(api, '3'); await store.load('ru')
  store.setAnswer('x'.repeat(5001)); await store.submit(); assert.equal(store.getSnapshot().fieldError, true)
  assert.equal(calls.some(call => call.method === 'submit'), false)
  const hold = deferred<SubmittedPractice>(); api.submit = () => hold.promise
  store.setAnswer('typed'); const sending = store.submit(); store.invalidate(); hold.resolve(submitted); await sending
  assert.equal(store.getSnapshot().answer, ''); assert.equal(store.getSnapshot().item, null)
})

for (const language of ['ru', 'en'] as const) test(`restart creates a new work in saved language and preserves the old result: ${language}`, async () => {
  const { api, calls } = fixture()
  const saved = { ...submitted, submitted_language: language }
  api.get = async () => saved
  api.start = async (...args) => { calls.push({ method: 'start', args }); return { ...pending, submission_id: '4', language: args[1] } }
  const store = new SubmissionStore(api, '3'); await store.load(language === 'ru' ? 'en' : 'ru')
  await store.restart()
  assert.equal(store.getSnapshot().kind, 'restarted')
  assert.deepEqual(store.getSnapshot().nextSubmission, { id: '4', language })
  assert.deepEqual(store.getSnapshot().item, saved)
  assert.equal(store.getSnapshot().answer, '')
  assert.deepEqual(calls, [{ method: 'start', args: ['1', language] }])
})

test('restart is single-flight and cannot be replaced by a translation GET', async () => {
  const { api } = fixture(); api.get = async () => submitted
  const hold = deferred<PendingPractice>(); let starts = 0
  api.start = async () => { starts++; return hold.promise }
  const store = new SubmissionStore(api, '3'); await store.load('ru')
  const first = store.restart(); await store.restart(); await store.load('en')
  assert.equal(starts, 1)
  assert.equal(store.getSnapshot().kind, 'restarting')
  assert.deepEqual(store.getSnapshot().item, submitted)
  hold.resolve({ ...pending, submission_id: '4' }); await first
  await store.restart()
  assert.equal(starts, 1)
  assert.equal(store.getSnapshot().nextSubmission?.id, '4')
})

test('restart does not discard an unsubmitted draft or start a new work from it', async () => {
  const { api, calls } = fixture()
  const store = new SubmissionStore(api, '3'); await store.load('ru'); store.setAnswer('unfinished')
  await store.restart()
  assert.equal(store.getSnapshot().kind, 'ready')
  assert.equal(store.getSnapshot().answer, 'unfinished')
  assert.equal(calls.some(call => call.method === 'start' || call.method === 'delete'), false)
})

for (const [status, code] of [[404, 'not_found'], [403, 'practice_locked'], [403, 'forbidden']] as const) {
  test(`restart refusal ${code} keeps the saved result and blocks further starts until reload`, async () => {
    const { api } = fixture(); api.get = async () => submitted
    let starts = 0; api.start = async () => { starts++; throw error(status, code) }
    const store = new SubmissionStore(api, '3'); await store.load('ru'); await store.restart()
    assert.equal(store.getSnapshot().kind, 'result')
    assert.deepEqual(store.getSnapshot().item, submitted)
    assert.equal(store.getSnapshot().restartBlocked, true)
    assert.ok(store.getSnapshot().message)
    await store.restart(); assert.equal(starts, 1)
    await store.load('ru'); assert.equal(store.getSnapshot().restartBlocked, undefined)
    api.start = async () => ({ ...pending, submission_id: '4' })
    await store.restart(); assert.equal(store.getSnapshot().kind, 'restarted')
  })
}

for (const code of ['csrf_failed', 'validation_error']) test(`restart ${code} permits an explicit retry without removing the result`, async () => {
  const { api } = fixture(); api.get = async () => submitted
  let starts = 0; api.start = async () => { starts++; if (starts === 1) throw error(code === 'csrf_failed' ? 403 : 400, code); return { ...pending, submission_id: '4' } }
  const store = new SubmissionStore(api, '3'); await store.load('ru'); await store.restart()
  assert.equal(store.getSnapshot().kind, 'result')
  assert.deepEqual(store.getSnapshot().item, submitted)
  assert.equal(starts, 1)
  await store.restart(); assert.equal(starts, 2)
  assert.equal(store.getSnapshot().kind, 'restarted')
})

test('lost restart response is never retried automatically; only a warned explicit new start is allowed', async () => {
  const { api } = fixture(); api.get = async () => submitted
  let starts = 0; api.start = async () => { starts++; if (starts === 1) throw error(0, 'network_error'); return { ...pending, submission_id: '4' } }
  const store = new SubmissionStore(api, '3'); await store.load('ru'); await store.restart()
  assert.equal(store.getSnapshot().kind, 'restart_uncertain')
  assert.deepEqual(store.getSnapshot().item, submitted)
  assert.ok(store.getSnapshot().message)
  await store.restart(); await store.load('en')
  assert.equal(starts, 1)
  assert.equal(store.getSnapshot().kind, 'restart_uncertain')
  await store.restart(true)
  assert.equal(starts, 2)
  assert.equal(store.getSnapshot().kind, 'restarted')
})

test('restart clears local user state after session loss', async () => {
  const { api } = fixture(); api.get = async () => submitted
  api.start = async () => { throw error(403, 'authentication_required') }
  const store = new SubmissionStore(api, '3'); await store.load('ru'); await store.restart()
  assert.equal(store.getSnapshot().kind, 'authentication')
  assert.equal(store.getSnapshot().item, null)
  assert.equal(store.getSnapshot().nextSubmission, undefined)
})

test('restart rejects an old or unrelated new identity without losing the saved result', async () => {
  for (const value of [pending, { ...pending, submission_id: '4', topic_id: '99' }, { ...pending, submission_id: '4', language: 'en' as const }]) {
    const { api } = fixture(); api.get = async () => submitted; api.start = async () => value
    const store = new SubmissionStore(api, '3'); await store.load('ru'); await store.restart()
    assert.equal(store.getSnapshot().kind, 'restart_uncertain')
    assert.equal(store.getSnapshot().nextSubmission, undefined)
    assert.deepEqual(store.getSnapshot().item, submitted)
  }
})

test('a late restart response cannot restore a disposed work or navigate to a new one', async () => {
  const { api } = fixture(); api.get = async () => submitted
  const hold = deferred<PendingPractice>(); api.start = async () => hold.promise
  const store = new SubmissionStore(api, '3'); await store.load('ru')
  const first = store.restart(); store.invalidate()
  hold.resolve({ ...pending, submission_id: '4' }); await first
  assert.equal(store.getSnapshot().kind, 'loading')
  assert.equal(store.getSnapshot().item, null)
  assert.equal(store.getSnapshot().nextSubmission, undefined)
})
