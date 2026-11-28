import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createApiClient, ApiError } from '../src/api/client.ts'
import { ContractError, topicReading, sectionArticle, sectionRead } from '../src/api/decoders.ts'
import type { SectionRead, TopicReading } from '../src/api/types.ts'
import { LearningStore } from '../src/learning/model.ts'
import { SectionReads } from '../src/learning/reading.ts'
import type { LearningApi } from '../src/learning/model.ts'
import { StartStore } from '../src/assessment/model.ts'

const at = '2026-11-27T10:00:00Z'
const initial: TopicReading = {
  topic_id: '12', title: 'Тема', language: 'ru', progress_generation: '1',
  reading: { total_sections: 2, read_sections: 0, is_read: false, completion_contribution: 0 },
  sections: [{ section_id: '101', position: 10, title: 'Первый', read_at: null },
    { section_id: '102', position: 20, title: 'Второй', read_at: null }],
}
const first: SectionRead = { topic_id: '12', section_id: '101', read_at: at, progress_generation: '1',
  reading: { total_sections: 2, read_sections: 1, is_read: false, completion_contribution: 15 } }
const detail = { topic_id: '12', topic_title: 'Тема', language: 'en', progress_generation: '1',
  section: { section_id: '101', position: 10, title: 'First', article_body: '  Body\r\n', read_at: null },
  previous_section_id: null, next_section_id: '102', reading: initial.reading }
const response = (data: unknown, status = 200) => new Response(JSON.stringify({ data }), {
  status, headers: { 'Content-Type': 'application/json' },
})

test('new reading decoders preserve the exact public DTO and server contribution', () => {
  assert.deepEqual(topicReading(initial), initial)
  assert.deepEqual(sectionArticle(detail), detail)
  assert.deepEqual(sectionRead(first), first)
})
for (const key of ['revision', 'user_id', 'expected_answer', 'snapshot', 'server_key', 'is_correct']) {
  test(`reading decoders reject private field ${key} instead of retaining it`, () => {
    assert.throws(() => topicReading({ ...initial, [key]: 'private' }), ContractError)
    assert.throws(() => topicReading({ ...initial, sections: [{ ...initial.sections[0], [key]: 'private' }, initial.sections[1]] }), ContractError)
    assert.throws(() => sectionArticle({ ...detail, section: { ...detail.section, [key]: 'private' } }), ContractError)
    assert.throws(() => sectionRead({ ...first, [key]: 'private' }), ContractError)
  })
}
test('reading decoders reject missing, duplicate and inconsistent section states', () => {
  for (const invalid of [
    { ...initial, sections: [] }, { ...initial, sections: [initial.sections[0], initial.sections[0]] },
    { ...initial, sections: [...initial.sections].reverse() },
    { ...initial, reading: { ...initial.reading, read_sections: 3 } },
    { ...initial, reading: { ...initial.reading, is_read: true } },
    { ...initial, progress_generation: '0' },
  ]) assert.throws(() => topicReading(invalid), ContractError)
  assert.throws(() => sectionRead({ ...first, read_at: null }), ContractError)
})
test('reading GETs and section POST use exact paths, credentials, CSRF and generation', async () => {
  const calls: { url: string; init: RequestInit | undefined }[] = []
  const api = createApiClient({ baseUrl: '/api/v1/', origin: 'http://127.0.0.1:5173', fetch: async (input, init) => {
    calls.push({ url: String(input), init })
    const path = new URL(String(input)).pathname
    if (path.endsWith('/auth/csrf/')) return response({ csrf_token: 'synthetic' })
    if (path.endsWith('/completion-progress/')) return response({ progress_generation: '1', overall_completion_progress: 0, topics: [] })
    if (path.endsWith('/reading/')) return response({ ...initial, language: 'en' })
    if (path.endsWith('/read/')) return response(first)
    return response(detail)
  } })
  assert.equal((await api.learning.reading('12', 'en')).language, 'en')
  assert.equal((await api.learning.section('12', '101', 'en')).section.section_id, '101')
  await api.progress.markSectionRead('12', '101')
  assert.equal(calls[0].url, 'http://127.0.0.1:5173/api/v1/topics/12/reading/?language=en')
  assert.equal(calls[1].url, 'http://127.0.0.1:5173/api/v1/topics/12/sections/101/?language=en')
  const write = calls.at(-1)!
  assert.equal(write.url, 'http://127.0.0.1:5173/api/v1/topics/12/sections/101/read/')
  assert.equal(write.init?.method, 'POST')
  assert.equal(write.init?.body, '{}')
  assert.equal(new Headers(write.init?.headers).get('X-CSRFToken'), 'synthetic')
  assert.equal(new Headers(write.init?.headers).get('X-Progress-Generation'), '1')
  assert.ok(calls.every(call => call.init?.credentials === 'include'))
  assert.equal(calls.filter(call => call.init?.method === 'POST').length, 1)
})
test('separate reader marks only its selected section and preserves pending during a language switch', async () => {
  const calls: string[] = []
  let finish!: (value: SectionRead) => void
  const api: LearningApi = {
    learning: {
      catalog: async () => [],
      section: async (_id, sectionId, language = 'ru') => ({ ...detail, language,
        section: { ...initial.sections.find(section => section.section_id === sectionId)!, article_body: 'Body' } }),
      terms: async () => [], reading: async (_id, language = 'ru') => ({ ...initial, language }),
    },
    progress: { markSectionRead: async (_id, sectionId) => {
      calls.push(sectionId)
      if (sectionId === '101') return new Promise(resolve => { finish = resolve })
      return { ...first, section_id: sectionId, reading: { total_sections: 2, read_sections: 2, is_read: true, completion_contribution: 30 } }
    } },
  }
  const reads = new SectionReads(api); reads.bindOwner('learner-1')
  const store = new LearningStore(api, { topicId: '12', language: 'ru' }, reads)
  await store.load()
  await store.markRead() // No implicit whole-topic operation for multiple sections.
  assert.deepEqual(calls, [])
  await store.load({ topicId: '12', sectionId: '101', language: 'ru' })
  const pending = store.markRead('101')
  await store.load({ topicId: '12', sectionId: '101', language: 'en' })
  await Promise.all([store.markRead('101'), store.markRead('102'), store.refreshRead()])
  assert.deepEqual(calls, ['101'])
  finish(first)
  await pending
  const partial = store.getSnapshot().read
  assert.equal(partial.kind, 'ready')
  if (partial.kind === 'ready') {
    assert.equal(partial.complete, false)
    assert.deepEqual(partial.sections, { '101': at, '102': null })
  }
  await store.markRead('101')
  await store.load({ topicId: '12', sectionId: '102', language: 'en' })
  await store.markRead('102')
  assert.deepEqual(calls, ['101', '102'])
  const complete = store.getSnapshot().read
  assert.ok(complete.kind === 'ready' && complete.complete)
})
test('start gate is a confirmed refusal, not an uncertain newly created attempt', async () => {
  const store = new StartStore({
    learning: { article: async () => ({ topic_id: '12', title: 'Тема', language: 'ru', article_body: 'Body' }) },
    assessment: { start: async () => { throw new ApiError({ status: 403, code: 'section_read_required', message: 'untrusted', kind: 'http' }) } },
  }, '12')
  await store.load('ru')
  await store.start()
  const state = store.getSnapshot()
  assert.equal(state.kind, 'ready')
  if (state.kind === 'ready') assert.equal(state.message, 'Сначала прочитайте все опубликованные разделы темы.')
})
