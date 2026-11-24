import assert from 'node:assert/strict'
import test from 'node:test'
import { ApiError, createApiClient } from '../src/api/client.ts'
import * as decode from '../src/api/decoders.ts'
import type { CompletionProgress, Progress } from '../src/api/types.ts'

const origin = 'http://127.0.0.1:5173'
const resetId = '00000000-0000-4000-8000-000000000034'
const mark: Progress = { topic_id: '1', article_read_at: '2026-11-23T10:00:00Z', best_result: null, mastered: false }
const empty = (generation = '1'): CompletionProgress => ({
  progress_generation: generation, overall_completion_progress: 0, topics: [],
})
const complete: CompletionProgress = { ...empty(), overall_completion_progress: 65, topics: [{
  topic_id: '1', article_read_at: mark.article_read_at, test: { status: 'passed',
    best_result: { correct_count: 4, total_count: 5, percentage: 80 } },
  practice: { task_id: '2', status: 'unattempted' }, completion_progress: 65, mastered: true,
}] }
const json = (data: unknown) => Response.json({ data })
const refusal = (code: string, status = 409) => Response.json({ error: { code, message: 'Безопасный отказ.' } }, { status })
const isReset = (error: unknown) => error instanceof ApiError && error.status === 409 && error.code === 'progress_reset'
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}
type Call = { path: string; init: RequestInit }
function fixture(reply: (call: Call) => Response | Promise<Response>, onProgressReset?: (reason: 'reset' | 'session') => void) {
  const calls: Call[] = []
  const api = createApiClient({ baseUrl: '/api/v1/', origin, onProgressReset, fetch: async (input, init) => {
    const call = { path: new URL(String(input)).pathname.slice('/api/v1/'.length), init: init! }
    calls.push(call)
    if (call.path === 'auth/csrf/') return json({ csrf_token: 'synthetic-in-memory-value' })
    return reply(call)
  } })
  return { api, calls, posts: () => calls.filter(call => call.init.method === 'POST') }
}

test('completion and reset decode the exact public contract, including null Practice', () => {
  assert.deepEqual(decode.completionProgress(complete), complete)
  assert.deepEqual(decode.completionProgress(empty('9223372036854775807')), empty('9223372036854775807'))
  const noPractice = { ...complete, topics: [{ ...complete.topics[0], practice: null }] }
  assert.deepEqual(decode.completionProgress(noPractice), noPractice)
  assert.deepEqual(decode.resetProgress({ progress_generation: '2' }), { progress_generation: '2' })
})

for (const invalid of ['', '0', '01', '+1', '-1', '1.0', ' 1', '9223372036854775808', 1, null]) {
  test(`invalid generation is rejected: ${JSON.stringify(invalid)}`, () => {
    assert.throws(() => decode.completionProgress({ ...empty(), progress_generation: invalid }), decode.ContractError)
    assert.throws(() => decode.resetProgress({ progress_generation: invalid }), decode.ContractError)
  })
}

test('strict completion decoders reject private fields, counts extensions and inconsistent activity status', () => {
  for (const field of ['expected_answer', 'snapshot', 'server_key', 'user_id', 'revision', 'counts']) {
    for (const value of [
      { ...complete, [field]: 'private' },
      { ...complete, topics: [{ ...complete.topics[0], [field]: 'private' }] },
      { ...complete, topics: [{ ...complete.topics[0], test: { ...complete.topics[0].test, [field]: 'private' } }] },
      { ...complete, topics: [{ ...complete.topics[0], practice: { ...complete.topics[0].practice, [field]: 'private' } }] },
    ]) assert.throws(() => decode.completionProgress(value), decode.ContractError)
  }
  for (const status of ['unattempted', 'failed', 'unknown']) {
    assert.throws(() => decode.completionProgress({ ...complete, topics: [{ ...complete.topics[0],
      test: { ...complete.topics[0].test, status },
    }] }), decode.ContractError)
  }
  for (const value of [-1, 101, NaN, Infinity, '65']) {
    assert.throws(() => decode.completionProgress({ ...complete, overall_completion_progress: value }), decode.ContractError)
  }
})

test('two progress writes share generation GET and retain credentials/CSRF with no automatic retry', async () => {
  const metadata = deferred<Response>()
  const entered = deferred<void>()
  const f = fixture(call => {
    if (call.path === 'completion-progress/') { entered.resolve(); return metadata.promise }
    return json(mark)
  })
  const pending = [f.api.progress.markRead('1'), f.api.progress.markRead('2')]
  await entered.promise
  assert.equal(f.posts().length, 0)
  metadata.resolve(json(empty('7')))
  await Promise.all(pending)
  assert.equal(f.calls.filter(call => call.path === 'completion-progress/').length, 1)
  assert.equal(f.posts().length, 2)
  for (const call of f.posts()) {
    assert.equal(new Headers(call.init.headers).get('X-Progress-Generation'), '7')
    assert.ok(new Headers(call.init.headers).has('X-CSRFToken'))
    assert.equal(call.init.credentials, 'include')
    assert.equal(call.init.body, '{}')
  }
})

test('legacy progress GET establishes the generation before an automatic read can use its result', async () => {
  const f = fixture(call => call.path === 'completion-progress/' ? json(empty('3')) :
    call.path === 'progress/' ? json([]) : json(mark))
  assert.deepEqual(await f.api.progress.current(), [])
  await f.api.progress.markRead('1')
  assert.deepEqual(f.calls.map(call => call.path), ['completion-progress/', 'progress/', 'auth/csrf/', 'topics/1/read/'])
  assert.equal(new Headers(f.posts()[0].init.headers).get('X-Progress-Generation'), '3')
})

test('stale POST blocks further writes until explicit GET; no fresh generation or replay on 409', async () => {
  let notices = 0
  let generation = '1'
  let reject = true
  const f = fixture(call => call.path === 'completion-progress/' ? json(empty(generation)) :
    reject ? refusal('progress_reset') : json(mark), () => { notices++ })
  await assert.rejects(f.api.progress.markRead('1'), isReset)
  await assert.rejects(f.api.progress.markRead('1'), isReset)
  assert.equal(f.posts().length, 1)
  assert.equal(f.calls.filter(call => call.path === 'completion-progress/').length, 1)
  assert.equal(notices, 1)
  generation = '2'
  reject = false
  await f.api.progress.completion()
  await f.api.progress.markRead('1')
  assert.equal(f.posts().length, 2)
  assert.equal(new Headers(f.posts()[1].init.headers).get('X-Progress-Generation'), '2')
})

test('reset uses explicit original generation and UUID; transport retry never becomes a new reset', async () => {
  let notices = 0
  const f = fixture(call => {
    assert.equal(call.path, 'progress/reset/')
    return json({ progress_generation: '8' })
  }, () => { notices++ })
  const first = await f.api.progress.reset('reset_all_progress', resetId, '7')
  const retry = await f.api.progress.reset('reset_all_progress', resetId, '7')
  assert.deepEqual(first, { progress_generation: '8' })
  assert.deepEqual(retry, first)
  assert.equal(f.posts().length, 2)
  assert.equal(notices, 1)
  for (const call of f.posts()) {
    assert.equal(new Headers(call.init.headers).get('X-Progress-Generation'), '7')
    assert.deepEqual(JSON.parse(String(call.init.body)), { confirmation: 'reset_all_progress', request_id: resetId })
  }
})

test('uncertain reset blocks an old end marker without automatic refresh or retry', async () => {
  let notices = 0
  const f = fixture(() => { throw new TypeError('Synthetic lost response') }, () => { notices++ })
  await assert.rejects(f.api.progress.reset('reset_all_progress', resetId, '1'), error =>
    error instanceof ApiError && error.code === 'network_error')
  await assert.rejects(f.api.progress.markRead('1'), isReset)
  assert.equal(f.posts().length, 1)
  assert.equal(notices, 1)
})

test('late private GET response is discarded after reset, including a delayed response body', async () => {
  const body = deferred<string>()
  const entered = deferred<void>()
  const f = fixture(call => {
    if (call.path === 'progress/reset/') return json({ progress_generation: '2' })
    const response = json([])
    response.text = () => { entered.resolve(); return body.promise }
    return response
  })
  const history = f.api.assessment.history()
  const rejected = assert.rejects(history, isReset)
  await entered.promise
  await f.api.progress.reset('reset_all_progress', resetId, '1')
  body.resolve(JSON.stringify({ data: [] }))
  await rejected
})

test('auth requests never send generation; a session change invalidates the cached owner generation', async () => {
  let generation = '5'
  const f = fixture(call => {
    if (call.path === 'completion-progress/') return json(empty(generation))
    if (call.path.startsWith('auth/')) return json({ user_id: '9', email: 'synthetic@example.invalid' })
    return json(mark)
  })
  await f.api.progress.completion()
  await f.api.auth.login('synthetic@example.invalid', 'synthetic-input')
  generation = '1'
  await f.api.progress.markRead('1')
  assert.equal(new Headers(f.posts()[0].init.headers).has('X-Progress-Generation'), false)
  assert.equal(new Headers(f.posts()[1].init.headers).get('X-Progress-Generation'), '1')
  assert.equal(f.calls.filter(call => call.path === 'completion-progress/').length, 2)
})

test('cross-tab signal contains no personal data and blocks stale writes until explicit reopening', async t => {
  const prior = Object.getOwnPropertyDescriptor(globalThis, 'window')
  const channels: Channel[] = []
  let pagehide: (() => void) | undefined
  class Channel extends EventTarget {
    messages: unknown[] = []
    closed = false
    readonly name: string
    constructor(name: string) { super(); this.name = name; channels.push(this) }
    postMessage(value: unknown) { this.messages.push(value) }
    close() { this.closed = true }
    receive(data: unknown) { this.dispatchEvent(new MessageEvent('message', { data })) }
  }
  Object.defineProperty(globalThis, 'window', { configurable: true, value: {
    BroadcastChannel: Channel, addEventListener: (event: string, listener: () => void) => { if (event === 'pagehide') pagehide = listener },
  } })
  t.after(() => { if (prior) Object.defineProperty(globalThis, 'window', prior); else Reflect.deleteProperty(globalThis, 'window') })
  let notices = 0
  const reasons: string[] = []
  const f = fixture(call => call.path === 'completion-progress/' ? json(empty()) : json({ progress_generation: '2' }),
    reason => { notices++; reasons.push(reason) })
  await f.api.progress.completion()
  assert.equal(channels[0].name, 'qil-progress-state')
  channels[0].receive('progress-reset')
  await assert.rejects(f.api.progress.markRead('1'), isReset)
  assert.equal(f.posts().length, 0)
  await f.api.progress.reset('reset_all_progress', resetId, '1')
  assert.deepEqual(channels[0].messages, ['progress-reset'])
  assert.equal(notices, 1)
  channels[0].receive('session-changed')
  assert.equal(notices, 2, 'Session loss must notify even while reset is already blocking writes')
  assert.deepEqual(reasons, ['reset', 'session'])
  pagehide?.()
  assert.equal(channels[0].closed, true)
})
