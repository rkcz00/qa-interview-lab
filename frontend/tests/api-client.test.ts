import assert from 'node:assert/strict'
import { test } from 'node:test'

import { ApiError, createApiClient } from '../src/api/client.ts'
import type { ApiClient } from '../src/api/client.ts'
import type { Account, Article, PendingAttempt, Progress, SubmittedAttempt, Term } from '../src/api/types.ts'

const ORIGIN = 'http://127.0.0.1:5173'
const BASE = ORIGIN + '/api/v1/'
const TOKEN = 'synthetic-csrf-value-kept-in-memory'
const INPUT_SECRET = 'synthetic-credential-input'
const ACCOUNT: Account = { user_id: '7', email: 'learner@example.invalid' }
const ARTICLE: Article = { topic_id: '9', title: 'Тестирование', language: 'en', article_body: 'Article text' }
const TERM: Term = { term_id: '11', position: 1, language: 'ru', name: 'Термин', definition: 'Определение' }
const PENDING: PendingAttempt = {
  attempt_id: '12', topic_id: '9', status: 'in_progress', language: 'en', questions: [{
    question_id: '13', position: 1, question_type: 'single_choice', text: 'Question?', choices: [
      { choice_id: '14', position: 1, text: 'First' }, { choice_id: '15', position: 2, text: 'Second' },
    ],
  }],
}
const SUBMITTED: SubmittedAttempt = {
  attempt_id: '12', topic_id: '9', topic_title: 'Тестирование', status: 'submitted',
  submitted_language: 'en', submitted_at: '2026-01-01T00:00:00Z',
  result: { correct_count: 4, total_count: 5, percentage: 80 },
}
const PROGRESS: Progress = {
  topic_id: '9', article_read_at: '2026-01-01T00:00:00Z', best_result: SUBMITTED.result, mastered: true,
}

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json; charset=utf-8' } })
}

type Call = { url: string; init: RequestInit }
function fixture(reply: () => Response | Promise<Response>, baseUrl = '/api/v1/') {
  const calls: Call[] = []
  const fetch: typeof globalThis.fetch = async (input, init) => {
    const url = String(input)
    assert.ok(init)
    calls.push({ url, init })
    if (new URL(url).pathname.endsWith('/auth/csrf/')) return json({ data: { csrf_token: TOKEN } })
    return reply()
  }
  return { calls, api: createApiClient({ baseUrl, origin: ORIGIN, fetch }) }
}

function apiError(status: number, code: string, kind = 'http') {
  return (error: unknown) => error instanceof ApiError && error.status === status && error.code === code && error.kind === kind
}

const routes: {
  name: string; path: string; method: string; status?: number; value: unknown;
  invoke: (api: ApiClient) => Promise<unknown>; body?: unknown;
}[] = [
  { name: 'bootstrap', path: 'auth/csrf/', method: 'GET', value: null, invoke: api => api.auth.bootstrap() },
  { name: 'register', path: 'auth/register/', method: 'POST', status: 201, value: ACCOUNT,
    invoke: api => api.auth.register(ACCOUNT.email, INPUT_SECRET), body: { email: ACCOUNT.email, password: INPUT_SECRET } },
  { name: 'login', path: 'auth/login/', method: 'POST', value: ACCOUNT,
    invoke: api => api.auth.login(ACCOUNT.email, INPUT_SECRET), body: { email: ACCOUNT.email, password: INPUT_SECRET } },
  { name: 'logout', path: 'auth/logout/', method: 'POST', status: 204, value: null,
    invoke: api => api.auth.logout(), body: {} },
  { name: 'session', path: 'auth/me/', method: 'GET', value: ACCOUNT, invoke: api => api.auth.currentSession() },
  { name: 'catalog', path: 'topics/?language=ru', method: 'GET', value: [{ topic_id: '9', title: 'Тема' }],
    invoke: api => api.learning.catalog('ru') },
  { name: 'article', path: 'topics/9/?language=en', method: 'GET', value: ARTICLE,
    invoke: api => api.learning.article('9', 'en') },
  { name: 'terms', path: 'topics/9/terms/?language=ru', method: 'GET', value: [TERM],
    invoke: api => api.learning.terms('9', 'ru') },
  { name: 'start', path: 'topics/9/attempts/', method: 'POST', status: 201, value: PENDING,
    invoke: api => api.assessment.start('9', 'en'), body: { language: 'en' } },
  { name: 'get attempt', path: 'attempts/12/?language=ru', method: 'GET', value: { ...PENDING, language: 'ru' },
    invoke: api => api.assessment.get('12', 'ru') },
  { name: 'submit', path: 'attempts/12/submit/', method: 'POST', value: SUBMITTED,
    invoke: api => api.assessment.submit('12', 'en', [{ question_id: '13', choice_ids: ['14'] }]),
    body: { language: 'en', answers: [{ question_id: '13', choice_ids: ['14'] }] } },
  { name: 'history', path: 'attempts/', method: 'GET', value: [SUBMITTED], invoke: api => api.assessment.history() },
  { name: 'mark read', path: 'topics/9/read/', method: 'POST', value: PROGRESS,
    invoke: api => api.progress.markRead('9'), body: {} },
  { name: 'progress', path: 'progress/', method: 'GET', value: [PROGRESS], invoke: api => api.progress.current() },
]

for (const route of routes) {
  test(`contract: ${route.name}`, async () => {
    const { api, calls } = fixture(() => route.status === 204 ? new Response(null, { status: 204 }) : json({ data: route.value }, route.status))
    const value = await route.invoke(api)
    if (route.name === 'bootstrap' || route.status === 204) assert.equal(value, undefined)
    else assert.deepEqual(value, route.value)
    assert.equal(calls.length, route.method === 'POST' ? 2 : 1)
    const call = calls.at(-1)!
    assert.equal(call.url, BASE + route.path)
    assert.equal(call.init.method, route.method)
    for (const request of calls) {
      assert.equal(request.init.credentials, 'include')
      assert.equal(request.init.redirect, 'error')
      assert.equal(request.init.cache, 'no-store')
      assert.ok(request.init.signal instanceof AbortSignal)
      assert.equal(new Headers(request.init.headers).has('Cookie'), false)
    }
    const headers = new Headers(call.init.headers)
    if (route.method === 'POST') {
      assert.equal(calls[0].url, BASE + 'auth/csrf/')
      assert.equal(headers.get('X-CSRFToken') === TOKEN, true, 'Missing CSRF header')
      assert.equal(headers.get('Content-Type'), 'application/json')
      assert.equal(call.init.body === JSON.stringify(route.body), true, 'Unexpected request body')
    } else {
      assert.equal(headers.has('X-CSRFToken'), false)
      assert.equal(call.init.body, undefined)
    }
  })
}

test('omitted language uses the backend default without adding unrelated query parameters', async () => {
  const { api, calls } = fixture(() => json({ data: [] }))
  await api.learning.catalog()
  assert.equal(calls[0].url, BASE + 'topics/')
})

test('article and test language are independent, and a submitted attempt keeps its stored language', async () => {
  const { api, calls } = fixture(() => json({ data: ARTICLE }))
  await api.learning.article('9', 'en')
  const pending = fixture(() => json({ data: { ...PENDING, language: 'ru' } }, 201))
  await pending.api.assessment.start('9', 'ru')
  assert.equal(calls[0].url, BASE + 'topics/9/?language=en')
  assert.equal(pending.calls[1].init.body, JSON.stringify({ language: 'ru' }))
  const completed = fixture(() => json({ data: SUBMITTED }))
  assert.deepEqual(await completed.api.assessment.get('12', 'ru'), SUBMITTED)
  assert.equal(completed.calls[0].url, BASE + 'attempts/12/?language=ru')
})

test('URL comes from configuration and IDs are encoded as path segments', async () => {
  const { api, calls } = fixture(() => json({ data: ARTICLE }), '/proxy/api/v1')
  await api.learning.article('id /?#', 'ru')
  assert.equal(calls[0].url, ORIGIN + '/proxy/api/v1/topics/id%20%2F%3F%23/?language=ru')
})

for (const [label, baseUrl] of [
  ['external origin', 'https://outside.example.invalid/api/v1/'], ['protocol relative', '//outside.example.invalid/api/v1/'],
  ['embedded credentials', 'http://name:credential@127.0.0.1:5173/api/v1/'],
  ['query', '/api/v1/?token=hidden'], ['fragment', '/api/v1/#fragment'], ['empty', ''],
]) {
  test('invalid base URL is rejected before credentials can be sent: ' + label, () => {
    assert.throws(() => createApiClient({ baseUrl, origin: ORIGIN }), apiError(0, 'invalid_configuration', 'configuration'))
  })
}

for (const [status, code] of [
  [400, 'validation_error'], [400, 'invalid_credentials'], [403, 'csrf_failed'], [403, 'authentication_required'],
  [403, 'already_authenticated'], [404, 'not_found'], [409, 'attempt_already_submitted'], [500, 'internal_error'],
] as const) {
  test(`HTTP ${status} ${code} is normalized without retaining request data`, async () => {
    const { api } = fixture(() => json({ error: { code, message: 'Ошибка запроса.', fields: { email: ['Некорректный email.'] } } }, status))
    await assert.rejects(api.auth.register(ACCOUNT.email, INPUT_SECRET), error => {
      assert.ok(apiError(status, code)(error))
      if (!(error instanceof ApiError)) return false
      assert.equal(error.message, 'Ошибка запроса.')
      assert.deepEqual(error.fields, { email: ['Некорректный email.'] })
      assert.equal(JSON.stringify(error).includes(INPUT_SECRET) || JSON.stringify(error).includes(TOKEN), false)
      assert.equal('request' in error || 'response' in error || 'cause' in error, false)
      return true
    })
  })
}

test('string field messages are normalized to arrays', async () => {
  const { api } = fixture(() => json({ error: { code: 'validation_error', message: 'Ошибка.', fields: { email: 'Неверный email.' } } }, 400))
  await assert.rejects(api.auth.currentSession(), error => {
    assert.ok(error instanceof ApiError)
    assert.deepEqual(error.fields, { email: ['Неверный email.'] })
    return true
  })
})

test('login rotation is followed by a fresh bootstrap before the next unsafe request', async () => {
  let bootstraps = 0
  const sent: boolean[] = []
  const fetch: typeof globalThis.fetch = async (input, init) => {
    if (String(input).endsWith('/auth/csrf/')) return json({ data: { csrf_token: 'synthetic-' + ++bootstraps } })
    sent.push(new Headers(init?.headers).get('X-CSRFToken') === 'synthetic-' + bootstraps)
    return String(input).endsWith('/logout/') ? new Response(null, { status: 204 }) : json({ data: ACCOUNT })
  }
  const api = createApiClient({ baseUrl: '/api/v1/', origin: ORIGIN, fetch })
  await api.auth.login(ACCOUNT.email, INPUT_SECRET)
  await api.auth.logout()
  assert.equal(bootstraps, 2)
  assert.deepEqual(sent, [true, true])
  assert.equal(JSON.stringify(api).includes(TOKEN) || JSON.stringify(api).includes(INPUT_SECRET), false)
})

test('overlapping bootstraps share one in-flight request', async () => {
  const { api, calls } = fixture(() => json({ data: ACCOUNT }))
  assert.deepEqual(await Promise.all([api.auth.bootstrap(), api.auth.bootstrap()]), [undefined, undefined])
  assert.equal(calls.length, 1)
})

test('the configured timeout aborts an unfinished request', async () => {
  let aborted = false
  const fetch: typeof globalThis.fetch = (_input, init) => new Promise((_resolve, reject) => {
    const watchdog = setTimeout(() => reject(new Error('Abort signal was not delivered')), 1000)
    init?.signal?.addEventListener('abort', () => {
      clearTimeout(watchdog)
      aborted = true
      reject(init.signal?.reason)
    }, { once: true })
  })
  const api = createApiClient({ baseUrl: '/api/v1/', origin: ORIGIN, fetch, timeoutMs: 10 })
  await assert.rejects(api.auth.currentSession(), apiError(0, 'network_error', 'network'))
  assert.equal(aborted, true)
})

test('both public question types and multiple selected IDs follow the server contract', async () => {
  const multiple = { ...PENDING.questions[0], question_id: '21', question_type: 'multiple_choice' as const }
  const pending = { ...PENDING, questions: [PENDING.questions[0], multiple] }
  const read = fixture(() => json({ data: pending }))
  assert.deepEqual(await read.api.assessment.get('12'), pending)
  const submit = fixture(() => json({ data: SUBMITTED }))
  await submit.api.assessment.submit('12', 'ru', [{ question_id: '21', choice_ids: ['14', '15'] }])
  assert.equal(submit.calls[1].init.body, JSON.stringify({ language: 'ru', answers: [{ question_id: '21', choice_ids: ['14', '15'] }] }))
})

test('CSRF bootstrap failure prevents POST and is not retried automatically', async () => {
  const calls: string[] = []
  const fetch: typeof globalThis.fetch = async input => {
    calls.push(String(input))
    return json({ error: { code: 'csrf_failed', message: 'CSRF отказ.' } }, 403)
  }
  const api = createApiClient({ baseUrl: '/api/v1/', origin: ORIGIN, fetch })
  await assert.rejects(api.progress.markRead('9'), apiError(403, 'csrf_failed'))
  assert.deepEqual(calls, [BASE + 'auth/csrf/'])
})

test('an unsafe failure is surfaced without repeating a potentially mutating request', async () => {
  const { api, calls } = fixture(() => json({ error: { code: 'csrf_failed', message: 'CSRF отказ.' } }, 403))
  await assert.rejects(api.assessment.start('9', 'ru'), apiError(403, 'csrf_failed'))
  assert.equal(calls.length, 2)
})

test('failed bootstrap is cleared so a later explicit action can try again', async () => {
  let calls = 0
  const fetch: typeof globalThis.fetch = async () => {
    if (++calls === 1) throw new TypeError('Synthetic transport failure')
    return json({ data: { csrf_token: TOKEN } })
  }
  const api = createApiClient({ baseUrl: '/api/v1/', origin: ORIGIN, fetch })
  await assert.rejects(api.auth.bootstrap(), apiError(0, 'network_error', 'network'))
  await api.auth.bootstrap()
  assert.equal(calls, 2)
})

for (const errorName of ['TypeError', 'AbortError', 'TimeoutError']) {
  test(`transport ${errorName} has a safe ApiError message`, async () => {
    const { api } = fixture(() => { const error = new Error(INPUT_SECRET + TOKEN); error.name = errorName; throw error })
    await assert.rejects(api.auth.currentSession(), error => {
      assert.ok(apiError(0, 'network_error', 'network')(error))
      assert.equal(String(error).includes(INPUT_SECRET) || String(error).includes(TOKEN), false)
      return true
    })
  })
}

for (const [label, reply] of [
  ['HTML', () => new Response('<html>unexpected</html>', { status: 500 })],
  ['broken JSON', () => new Response('{', { headers: { 'Content-Type': 'application/json' } })],
  ['missing envelope', () => json(ACCOUNT)],
  ['wrong field type', () => json({ data: { ...ACCOUNT, user_id: 7 } })],
  ['unexpected success status', () => json({ data: ACCOUNT }, 201)],
  ['invalid error envelope', () => json({ error: { code: 1, message: null } }, 400)],
] as const) {
  test(`invalid response: ${label}`, async () => {
    const { api } = fixture(reply)
    await assert.rejects(api.auth.currentSession(), error => error instanceof ApiError && error.code === 'invalid_response')
  })
}

for (const field of ['password', 'password_hash', 'session_id', 'content_snapshot', 'server_key', 'revision']) {
  test(`account rejects unexpected sensitive field ${field}`, async () => {
    const { api } = fixture(() => json({ data: { ...ACCOUNT, [field]: 'private-value' } }))
    await assert.rejects(api.auth.currentSession(), apiError(200, 'invalid_response', 'protocol'))
  })
}

test('nested correct answers and internal snapshots never escape the client boundary', async () => {
  const pending = structuredClone(PENDING)
  const malformed = { ...pending, questions: [{ ...pending.questions[0], choices: [
    { ...pending.questions[0].choices[0], is_correct: true },
  ] }] }
  await assert.rejects(fixture(() => json({ data: malformed })).api.assessment.get('12'), apiError(200, 'invalid_response', 'protocol'))
  for (const value of [{ ...SUBMITTED, content_snapshot: {} }, { ...SUBMITTED, result: { ...SUBMITTED.result, server_key: 'private' } }]) {
    await assert.rejects(fixture(() => json({ data: value })).api.assessment.get('12'), apiError(200, 'invalid_response', 'protocol'))
  }
  const progress = { ...PROGRESS, best_result: { ...SUBMITTED.result, correct_answer: 'private' } }
  await assert.rejects(fixture(() => json({ data: [progress] })).api.progress.current(), apiError(200, 'invalid_response', 'protocol'))
  const invalidError = { error: { code: 'validation_error', message: 'Ошибка.', fields: { server_key: ['private'] } } }
  await assert.rejects(fixture(() => json(invalidError, 400)).api.auth.currentSession(), apiError(400, 'invalid_response', 'protocol'))
})

test('no persistent browser storage or cookie reading is used', async t => {
  for (const name of ['localStorage', 'sessionStorage', 'document'] as const) {
    const previous = Object.getOwnPropertyDescriptor(globalThis, name)
    Object.defineProperty(globalThis, name, { configurable: true, get() { throw new Error('Persistent access forbidden') } })
    t.after(() => { if (previous) Object.defineProperty(globalThis, name, previous); else Reflect.deleteProperty(globalThis, name) })
  }
  const { api } = fixture(() => json({ data: ACCOUNT }))
  await api.auth.bootstrap()
  await api.auth.login(ACCOUNT.email, INPUT_SECRET)
})
