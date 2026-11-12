import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ApiError } from '../src/api/client.ts'
import type { ApiClient } from '../src/api/client.ts'
import type { Attempt, Language, PendingAttempt, SubmittedAttempt } from '../src/api/types.ts'
import type { Destination, Route } from '../src/auth/routing.ts'
import { resolveRoute } from '../src/auth/routing.ts'
import { authDestination } from '../src/learning/routing.ts'
import { answerPayload, formatPercentage, publicResult, selectChoice } from '../src/assessment/answers.ts'
import type { Selection } from '../src/assessment/answers.ts'
import { AttemptStore, StartStore } from '../src/assessment/model.ts'
import { assessmentDestination, assessmentLocation } from '../src/assessment/routing.ts'

function pending(language: Language = 'ru'): PendingAttempt {
  return { attempt_id: '51', topic_id: '12', status: 'in_progress', language, questions: [
    { question_id: '2', position: 10, question_type: 'multiple_choice', text: language + ' multiple', choices: [
      { choice_id: '21', position: 10, text: language + ' first' }, { choice_id: '22', position: 20, text: language + ' second' },
    ] },
    { question_id: '1', position: 20, question_type: 'single_choice', text: language + ' single', choices: [
      { choice_id: '11', position: 10, text: language + ' first' }, { choice_id: '12', position: 20, text: language + ' second' },
    ] },
  ] }
}
const submitted = (): SubmittedAttempt => ({ attempt_id: '51', topic_id: '12', topic_title: 'Saved title', status: 'submitted',
  submitted_at: '2026-11-12T10:00:00Z', submitted_language: 'ru', result: { correct_count: 1, total_count: 2, percentage: 50 } })
const failure = (status: number, code: string) => new ApiError({ status, code, kind: status ? 'http' : 'network', message: 'Untrusted internal details' })
function mock() {
  const calls: { method: string; language?: Language; body?: string }[] = []
  const api: ApiClient['assessment'] = {
    start: async (_id, language) => { calls.push({ method: 'start', language }); return pending(language) },
    get: async (_id, language = 'ru') => { calls.push({ method: 'get', language }); return pending(language) },
    submit: async (_id, language, answers) => { calls.push({ method: 'submit', language, body: JSON.stringify(answers) }); return submitted() },
    history: async () => { calls.push({ method: 'history' }); return [] },
  }
  return { api, calls }
}
const tick = async () => { await new Promise<void>(resolve => setTimeout(resolve, 0)) }

test('single choice replaces the previous selection; multiple choice toggles an exact set', () => {
  const attempt = pending()
  let selected: Selection = new Map()
  selected = selectChoice(attempt, selected, '1', '11', true)
  selected = selectChoice(attempt, selected, '1', '12', true)
  assert.deepEqual(selected.get('1'), ['12'])
  selected = selectChoice(attempt, selected, '2', '21', true)
  selected = selectChoice(attempt, selected, '2', '22', true)
  selected = selectChoice(attempt, selected, '2', '21', true)
  assert.deepEqual(selected.get('2'), ['21', '22'])
  selected = selectChoice(attempt, selected, '2', '21', false)
  assert.deepEqual(selected.get('2'), ['22'])
})

test('answer payload contains only agreed fields, preserves snapshot order and includes skips', () => {
  const selected = new Map([['2', ['22', '21']]])
  const payload = answerPayload(pending(), selected)
  assert.deepEqual(payload, [{ question_id: '2', choice_ids: ['21', '22'] }, { question_id: '1', choice_ids: [] }])
  selected.get('2')?.push('21')
  assert.deepEqual(payload[0].choice_ids, ['21', '22'])
  assert.equal(Object.isFrozen(payload), true)
  assert.equal(Object.isFrozen(payload[0].choice_ids), true)
})

test('unknown, duplicate and multiple single-choice selections cannot become a payload', () => {
  for (const selected of [new Map([['missing', ['21']]]), new Map([['2', ['unknown']]]),
    new Map([['2', ['21', '21']]]), new Map([['1', ['11', '12']]])]) assert.throws(() => answerPayload(pending(), selected), RangeError)
  assert.throws(() => selectChoice(pending(), new Map(), '1', '21', true), RangeError)
})

test('test routes use their own language and only safe internal return targets', () => {
  assert.equal(resolveRoute('/topics/12/test'), '/topics/12/test')
  assert.equal(resolveRoute('/attempts/51'), '/attempts/51')
  assert.deepEqual(assessmentLocation('/topics/12/test', ''), { kind: 'start', id: '12', language: 'ru' })
  assert.deepEqual(assessmentLocation('/attempts/51', '?language=en'), { kind: 'attempt', id: '51', language: 'en' })
  assert.equal(assessmentDestination({ kind: 'start', id: '12', language: 'ru' }), '/topics/12/test')
  assert.equal(authDestination('/attempts/51?language=en'), '/attempts/51?language=en')
  assert.equal(authDestination('/topics/12/test?language=en'), '/topics/12/test?language=en')
  for (const search of ['?language=de', '?language=ru&language=en']) assert.equal(assessmentLocation('/attempts/51', search), null)
  for (const path of ['/attempts/%2Fbad', '/attempts/%2e%2e', '/topics/%ZZ/test']) assert.equal(assessmentLocation(path as Route, ''), null)
  assert.equal(authDestination('/attempts/51/submit' as Destination), '/session')
})

test('result projection contains only server aggregates and formats without calculating a grade', () => {
  const value = { ...submitted().result, server_key: 'not public', questions: ['not public'] }
  assert.deepEqual(publicResult(value), { correct_count: 1, total_count: 2, percentage: 50 })
  assert.equal(formatPercentage(3.13), '3,13%')
  assert.equal(formatPercentage(80), '80%')
})

test('start is explicit, double click is blocked and its language is frozen during creation', async () => {
  const { api, calls } = mock()
  let finish!: (value: PendingAttempt) => void
  api.start = async (_id, language) => { calls.push({ method: 'start', language }); return new Promise(resolve => { finish = resolve }) }
  const learning = { article: async (_id: string, language: Language = 'ru') => ({ topic_id: '12', language, title: 'Title', article_body: 'Body' }) }
  const store = new StartStore({ assessment: api, learning }, '12')
  await store.load('en')
  assert.equal(calls.length, 0)
  const first = store.start()
  await store.start()
  await store.load('ru')
  assert.equal(store.getSnapshot().kind, 'creating')
  assert.deepEqual(calls, [{ method: 'start', language: 'en' }])
  finish(pending('en'))
  await first
  assert.deepEqual(store.getSnapshot(), { kind: 'started', language: 'en', attemptId: '51' })
})

test('lost start response is not automatically retried or presented as a known failure', async () => {
  const { api, calls } = mock()
  api.start = async () => { calls.push({ method: 'start' }); throw failure(0, 'network_error') }
  const learning = { article: async () => ({ topic_id: '12', language: 'ru' as const, title: 'Title', article_body: 'Body' }) }
  const store = new StartStore({ assessment: api, learning }, '12')
  await store.load('ru')
  await store.start()
  await store.start()
  assert.equal(store.getSnapshot().kind, 'uncertain')
  assert.equal(calls.length, 1)
  await store.start(true)
  assert.equal(calls.length, 2)
})

test('attempt GET restores questions without starting a new attempt', async () => {
  const { api, calls } = mock()
  const store = new AttemptStore(api, '51')
  await store.load('en')
  const state = store.getSnapshot()
  assert.equal(state.kind, 'pending')
  if (state.kind === 'pending') { assert.equal(state.attempt.language, 'en'); assert.equal(state.selected.size, 0) }
  assert.deepEqual(calls, [{ method: 'get', language: 'en' }])
})

test('language changes preserve selected IDs and current question; clear does not affect other answers', async () => {
  const { api } = mock()
  const store = new AttemptStore(api, '51')
  await store.load('ru')
  store.choose('2', '21', true)
  store.move(1)
  store.choose('1', '11', true)
  await store.load('en')
  const state = store.getSnapshot()
  assert.equal(state.kind, 'pending')
  if (state.kind === 'pending') {
    assert.equal(state.index, 1)
    assert.equal(state.attempt.language, 'en')
    assert.deepEqual([...state.selected], [['2', ['21']], ['1', ['11']]])
  }
  store.clear()
  const cleared = store.getSnapshot()
  if (cleared.kind === 'pending') assert.deepEqual([...cleared.selected], [['2', ['21']]])
})

test('a successful submit sends agreed answers and removes questions and selections from result state', async () => {
  const { api, calls } = mock()
  const store = new AttemptStore(api, '51')
  await store.load('en')
  store.choose('2', '22', true)
  await store.submit()
  assert.deepEqual(calls.at(-1), { method: 'submit', language: 'en', body: '[{"question_id":"2","choice_ids":["22"]},{"question_id":"1","choice_ids":[]}]' })
  assert.deepEqual(store.getSnapshot(), { kind: 'result', result: submitted().result, notice: undefined })
  await store.submit()
  assert.equal(calls.filter(call => call.method === 'submit').length, 1)
})

test('double submit is blocked before the first network response', async () => {
  const { api, calls } = mock()
  let finish!: (value: SubmittedAttempt) => void
  api.submit = async () => { calls.push({ method: 'submit' }); return new Promise(resolve => { finish = resolve }) }
  const store = new AttemptStore(api, '51')
  await store.load('ru')
  const first = store.submit()
  await store.submit()
  store.choose('2', '21', true)
  assert.equal(store.getSnapshot().kind, 'sending')
  assert.equal(calls.filter(call => call.method === 'submit').length, 1)
  finish(submitted())
  await first
  assert.equal(store.getSnapshot().kind, 'result')
})

for (const [status, code, expected] of [[400, 'validation_error', 'pending'], [403, 'csrf_failed', 'pending'],
  [403, 'authentication_required', 'authentication'], [404, 'not_found', 'not_found']] as const) {
  test(`submit ${code} follows the documented contract without rendering internal errors`, async () => {
    const { api } = mock()
    api.submit = async () => { throw failure(status, code) }
    const store = new AttemptStore(api, '51')
    await store.load('ru')
    store.choose('2', '21', true)
    await store.submit()
    const state = store.getSnapshot()
    assert.equal(state.kind, expected)
    assert.equal(JSON.stringify(state).includes('Untrusted internal details'), false)
    if (state.kind === 'pending') assert.deepEqual(state.selected.get('2'), ['21'])
  })
}

test('an interrupted response can be confirmed by GET without another submit', async () => {
  const { api, calls } = mock()
  let saved = false
  api.get = async (): Promise<Attempt> => saved ? submitted() : pending()
  api.submit = async () => { calls.push({ method: 'submit' }); saved = true; throw failure(0, 'network_error') }
  const store = new AttemptStore(api, '51')
  await store.load('ru')
  await store.submit()
  assert.equal(store.getSnapshot().kind, 'result')
  assert.equal(calls.length, 1)
})

test('uncertain submit freezes answers and language; explicit retry sends exactly the original payload', async () => {
  const { api, calls } = mock()
  api.submit = async (_id, language, answers) => {
    calls.push({ method: 'submit', language, body: JSON.stringify(answers) })
    if (calls.filter(call => call.method === 'submit').length === 1) throw failure(0, 'network_error')
    return submitted()
  }
  const store = new AttemptStore(api, '51')
  await store.load('ru')
  store.choose('2', '22', true)
  await store.submit()
  assert.equal(store.getSnapshot().kind, 'uncertain')
  store.choose('2', '21', true)
  await store.load('en')
  await store.submit()
  await store.retrySame()
  const writes = calls.filter(call => call.method === 'submit')
  assert.equal(writes.length, 2)
  assert.deepEqual(writes[0], writes[1])
  assert.equal(store.getSnapshot().kind, 'result')
})

test('409 fetches the saved result and never retries the changed submission', async () => {
  const { api, calls } = mock()
  let saved = false
  api.get = async (): Promise<Attempt> => saved ? submitted() : pending()
  api.submit = async () => { calls.push({ method: 'submit' }); saved = true; throw failure(409, 'attempt_already_submitted') }
  const store = new AttemptStore(api, '51')
  await store.load('ru')
  await store.submit()
  await store.retrySame()
  const state = store.getSnapshot()
  assert.equal(state.kind, 'result')
  if (state.kind === 'result') assert.ok(state.notice)
  assert.equal(calls.length, 1)
})

test('409 with unavailable GET exposes no editable questions, grade or retry POST', async () => {
  const { api, calls } = mock()
  let conflict = false
  api.get = async () => { if (conflict) throw failure(0, 'network_error'); return pending() }
  api.submit = async () => { calls.push({ method: 'submit' }); conflict = true; throw failure(409, 'attempt_already_submitted') }
  const store = new AttemptStore(api, '51')
  await store.load('ru')
  await store.submit()
  const state = store.getSnapshot()
  assert.equal(state.kind, 'uncertain')
  if (state.kind === 'uncertain') assert.equal(state.canRetry, false)
  await store.retrySame()
  assert.equal(calls.length, 1)
})

test('old language responses and unmounted requests cannot overwrite the current attempt', async () => {
  const { api } = mock()
  const ready = new Map<Language, (value: Attempt) => void>()
  api.get = (_id, language = 'ru') => new Promise(resolve => { ready.set(language, resolve) })
  const store = new AttemptStore(api, '51')
  const old = store.load('ru')
  const current = store.load('en')
  ready.get('en')!(pending('en'))
  await current
  ready.get('ru')!(pending('ru'))
  await old
  const state = store.getSnapshot()
  if (state.kind === 'pending') assert.equal(state.attempt.language, 'en')
  const abandoned = store.load('ru')
  store.invalidate()
  ready.get('ru')!(pending())
  await abandoned
  assert.equal(store.getSnapshot().kind, 'loading')
})

test('a completed attempt is restored as only the saved aggregate result', async () => {
  const { api } = mock()
  api.get = async () => submitted()
  const store = new AttemptStore(api, '51')
  await store.load('en')
  assert.deepEqual(store.getSnapshot(), { kind: 'result', result: submitted().result, notice: undefined })
})

test('changed snapshot identity or question order cannot silently rebind the selected IDs', async () => {
  const { api } = mock()
  const store = new AttemptStore(api, '51')
  await store.load('ru')
  api.get = async () => ({ ...pending('en'), questions: [...pending('en').questions].reverse() })
  await store.load('en')
  assert.equal(store.getSnapshot().kind, 'error')
  await tick()
})
