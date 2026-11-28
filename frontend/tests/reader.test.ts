import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ApiError, createApiClient } from '../src/api/client.ts'
import type { Language, SectionArticle, SectionRead, TopicReading } from '../src/api/types.ts'
import { LearningStore } from '../src/learning/model.ts'
import type { LearningApi } from '../src/learning/model.ts'
import { SectionReads } from '../src/learning/reading.ts'
import { learningDestination, learningLocation, sectionFromHash } from '../src/learning/routing.ts'
import { resolveRoute } from '../src/auth/routing.ts'

const DATE_A = '2026-11-27T10:00:00Z', DATE_B = '2026-11-27T10:01:00Z'
const states = [
  { total_sections: 2, read_sections: 0, is_read: false, completion_contribution: 0 },
  { total_sections: 2, read_sections: 1, is_read: false, completion_contribution: 15 },
  { total_sections: 2, read_sections: 2, is_read: true, completion_contribution: 30 },
] as const
function toc(language: Language = 'ru'): TopicReading {
  return { topic_id: '12', title: language + ' topic', language, progress_generation: '1', reading: states[0], sections: [
    { section_id: '101', position: 10, title: language + ' section A', read_at: null },
    { section_id: '202', position: 30, title: language + ' section B', read_at: null },
  ] }
}
function article(id: string, language: Language): SectionArticle {
  return { topic_id: '12', topic_title: language + ' topic', language, progress_generation: '1',
    section: { ...toc(language).sections.find(s => s.section_id === id)!, article_body: language + ' selected body ' + id },
    previous_section_id: id === '101' ? null : '101', next_section_id: id === '101' ? '202' : null, reading: states[0] }
}
const saved = (id = '101', count = 1): SectionRead => ({ topic_id: '12', section_id: id, progress_generation: '1',
  read_at: id === '101' ? DATE_A : DATE_B, reading: states[count] })
function setup(onSaved: () => void = () => {}) {
  const calls: string[] = []
  const api: LearningApi = { learning: {
    catalog: async () => [],
    reading: async (_id, language = 'ru') => { calls.push('toc:' + language); return toc(language) },
    section: async (_id, id, language = 'ru') => { calls.push('section:' + id + ':' + language); return article(id, language) },
    terms: async (_id, language = 'ru') => { calls.push('terms:' + language); return [{ term_id: '1', position: 10, language, name: 'Term', definition: 'Definition' }] },
  }, progress: { markSectionRead: async (_id, id, generation) => { calls.push('post:' + id + ':' + generation); return saved(id) } } }
  const reads = new SectionReads(api, onSaved); reads.bindOwner('learner-A')
  const store = (id: string | null = '101', language: Language = 'ru') =>
    new LearningStore(api, { topicId: '12', sectionId: id, language }, reads)
  return { api, calls, reads, store }
}
const failure = () => new ApiError({ status: 0, code: 'network_error', kind: 'network', message: 'untrusted-private-value' })

test('section routes use only safe internal paths and retain the material language', () => {
  assert.equal(resolveRoute('/topics/12/sections/202'), '/topics/12/sections/202')
  assert.deepEqual(learningLocation('/topics/12/sections/202', '?language=en'), { topicId: '12', sectionId: '202', language: 'en' })
  assert.equal(learningDestination({ topicId: '12', sectionId: '202', language: 'en' }), '/topics/12/sections/202?language=en')
  assert.equal(learningDestination({ topicId: '12', sectionId: '202', language: 'en' }, null), '/topics/12?language=en')
  for (const path of ['/topics/12/sections/', '/topics/12/sections/202/extra', '//outside.invalid']) assert.equal(resolveRoute(path), null)
  for (const path of ['/topics/12/sections/%2foutside', '/topics/12/sections/%2e%2e', '/topics/12/sections/%ZZ'] as const) {
    assert.equal(learningLocation(path, ''), null)
  }
  assert.equal(sectionFromHash('#section-202'), '202')
  assert.equal(sectionFromHash('#https://outside.invalid'), null)
})

test('contents fetch metadata and glossary only; they never fetch bodies or write Read', async () => {
  const { calls, store } = setup(), contents = store(null, 'en')
  await contents.load()
  await contents.markRead('101')
  const content = contents.getSnapshot().content
  assert.equal(content.kind, 'topic')
  if (content.kind === 'topic') {
    assert.equal(content.article, null)
    assert.deepEqual(content.topic.sections.map(s => s.section_id), ['101', '202'])
    assert.equal(content.terms[0].language, 'en')
  }
  assert.deepEqual(calls, ['toc:en', 'terms:en'])
})

test('reader fetches exactly the selected body and uses public server neighbor IDs', async () => {
  const { calls, store } = setup(), reader = store('202', 'en')
  await reader.load()
  const content = reader.getSnapshot().content
  assert.equal(content.kind, 'topic')
  if (content.kind === 'topic') {
    assert.equal(content.article?.section.article_body, 'en selected body 202')
    assert.equal(content.article?.previous_section_id, '101')
    assert.equal(content.article?.next_section_id, null)
    assert.equal(content.terms[0].language, 'en')
  }
  assert.deepEqual(calls, ['toc:en', 'section:202:en', 'terms:en'])
  await reader.markRead('101')
  assert.equal(calls.some(c => c.startsWith('post:')), false)
})

test('held A survives reader unmount, B and A remount; one POST applies to A only', async () => {
  const { api, calls, reads, store } = setup()
  let finish!: (value: SectionRead) => void
  api.progress.markSectionRead = async (_topic, id, generation) => {
    calls.push('post:' + id + ':' + generation)
    return new Promise(resolve => { finish = resolve })
  }
  const a = store(); await a.load()
  const pending = a.markRead()
  a.invalidate()
  const b = store('202'); await b.load()
  await b.markRead('101')
  const back = store('101', 'en'); await back.load()
  await Promise.all([back.markRead(), back.markRead(), back.refreshRead()])
  assert.equal(reads.phase('12', '101'), 'pending')
  assert.deepEqual(calls.filter(c => c.startsWith('post:')), ['post:101:1'])
  finish(saved()); await pending
  assert.equal(reads.phase('12', '202'), 'unread')
  const read = back.getSnapshot().read
  assert.equal(read.kind, 'ready')
  if (read.kind === 'ready') {
    assert.deepEqual(read.sections, { '101': DATE_A, '202': null })
    assert.equal(read.complete, false)
    assert.equal(read.reading.completion_contribution, 15)
  }
})

test('different section flights may finish out of order without losing a first date or full Read', async () => {
  const { api, calls, store } = setup()
  const finish = new Map<string, (value: SectionRead) => void>()
  api.progress.markSectionRead = async (_topic, id) => {
    calls.push('post:' + id)
    return new Promise(resolve => { finish.set(id, resolve) })
  }
  const a = store(), b = store('202')
  await a.load(); const first = a.markRead()
  await b.load(); const second = b.markRead()
  finish.get('202')!(saved('202', 2)); await second
  finish.get('101')!(saved('101', 1)); await first
  const value = b.getSnapshot().read
  assert.equal(value.kind, 'ready')
  if (value.kind === 'ready') {
    assert.deepEqual(value.sections, { '101': DATE_A, '202': DATE_B })
    assert.deepEqual(value.reading, states[2])
  }
  assert.deepEqual(calls.filter(c => c.startsWith('post:')), ['post:101', 'post:202'])
})

test('a GET started before a successful POST cannot replace the confirmed state', async () => {
  const { api, store } = setup(), reader = store()
  await reader.load()
  let finish!: (value: TopicReading) => void
  api.learning.reading = async () => new Promise(resolve => { finish = resolve })
  const checking = reader.refreshRead()
  await reader.markRead()
  finish(toc()); await checking
  const value = reader.getSnapshot().read
  assert.equal(value.kind, 'ready')
  if (value.kind === 'ready') {
    assert.equal(value.sections['101'], DATE_A)
    assert.deepEqual(value.reading, states[1])
  }
})

test('failed POST requires explicit GET and explicit retry; translation never retries it', async () => {
  const { api, calls, store, reads } = setup(), reader = store()
  api.progress.markSectionRead = async () => { calls.push('post'); throw failure() }
  await reader.load(); await reader.markRead()
  await reader.load({ topicId: '12', sectionId: '101', language: 'en' })
  await reader.markRead()
  assert.equal(reads.phase('12', '101'), 'error')
  assert.equal(calls.filter(c => c === 'post').length, 1)
  await reader.refreshRead()
  assert.equal(reads.phase('12', '101'), 'retry')
  await reader.markRead()
  assert.equal(calls.filter(c => c === 'post').length, 1)
  assert.equal(JSON.stringify(reader.getSnapshot()).includes('untrusted-private-value'), false)
  api.progress.markSectionRead = async () => { calls.push('post'); return saved() }
  reader.allowRetry(); await reader.markRead()
  assert.equal(calls.filter(c => c === 'post').length, 2)
})

test('explicit GET can confirm a saved date after an uncertain POST without another write', async () => {
  let notifications = 0
  const { api, calls, store, reads } = setup(() => { notifications++ }), reader = store()
  api.progress.markSectionRead = async () => { calls.push('post'); throw failure() }
  await reader.load(); await reader.markRead()
  api.learning.reading = async () => ({ ...toc(), reading: states[1], sections: toc().sections.map(section =>
    section.section_id === '101' ? { ...section, read_at: DATE_A } : section) })
  await reader.refreshRead(); reader.allowRetry(); await reader.markRead()
  assert.equal(reads.phase('12', '101'), 'read')
  const value = reader.getSnapshot().read
  assert.equal(value.kind, 'ready')
  if (value.kind === 'ready') assert.equal(value.sections['101'], DATE_A)
  assert.equal(calls.filter(call => call === 'post').length, 1)
  assert.equal(notifications, 1)
  await reader.load()
  assert.equal(notifications, 1)
})

test('new Published section metadata changes aggregate Read while retaining existing dates', async () => {
  const { api, store, reads } = setup(), reader = store()
  await reader.load(); await reader.markRead()
  const full = { ...toc(), reading: states[2], sections: toc().sections.map(section =>
    ({ ...section, read_at: section.section_id === '101' ? DATE_A : DATE_B })) }
  reads.accept(full, reads.token())
  const updated = { ...full, reading: { total_sections: 3, read_sections: 2, is_read: false, completion_contribution: 20 },
    sections: [...full.sections, { section_id: '303', position: 40, title: 'New section', read_at: null }] }
  api.learning.reading = async () => updated
  await reader.load()
  const value = reader.getSnapshot().read
  assert.equal(value.kind, 'ready')
  if (value.kind === 'ready') {
    assert.equal(value.complete, false)
    assert.deepEqual(value.reading, updated.reading)
    assert.deepEqual(value.sections, { '101': DATE_A, '202': DATE_B, '303': null })
  }
})

for (const change of ['added', 'replaced'] as const) {
  test('late section POST preserves newer Published section metadata: ' + change, async () => {
    const { api, reads, store } = setup(), reader = store()
    let finish!: (value: SectionRead) => void
    api.progress.markSectionRead = async () => new Promise(resolve => { finish = resolve })
    await reader.load(); const writing = reader.markRead()
    const extra = { section_id: '303', position: 40, title: 'New section', read_at: null }
    const latest: TopicReading = change === 'added'
      ? { ...toc(), sections: [{ ...toc().sections[0], read_at: DATE_A }, toc().sections[1], extra],
          reading: { total_sections: 3, read_sections: 1, is_read: false, completion_contribution: 10 } }
      : { ...toc(), sections: [toc().sections[1], extra], reading: states[0] }
    api.learning.reading = async () => latest
    const contents = store(null); await contents.load()
    finish(saved()); await writing
    const read = contents.getSnapshot().read
    assert.equal(read.kind, 'ready')
    if (read.kind === 'ready') {
      assert.deepEqual(read.reading, latest.reading)
      assert.equal(read.complete, false)
      assert.deepEqual(Object.keys(read.sections), latest.sections.map(section => section.section_id))
    }
    assert.equal(reads.phase('12', '101'), 'read')
  })
}

for (const action of ['reset', 'owner', 'session'] as const) {
  test(action + ' invalidates old GET/POST and never restores previous private dates', async () => {
    const { api, reads, store } = setup(), reader = store()
    let finish!: (value: SectionRead) => void
    api.progress.markSectionRead = async () => new Promise(resolve => { finish = resolve })
    await reader.load(); const pending = reader.markRead()
    const token = reads.token()
    if (action === 'owner') reads.bindOwner('learner-B')
    else if (action === 'session') reads.expire()
    else reads.clear()
    finish(saved()); await pending
    assert.equal(reads.accept(toc(), token), false)
    assert.equal(reads.phase('12', '101'), 'unknown')
    assert.equal(reader.getSnapshot().read.kind, 'loading')
    if (action === 'session') assert.equal(reader.getSnapshot().content.kind, 'authentication')
  })
}

test('section POST keeps its original generation instead of fetching a newer one', async () => {
  const calls: { url: string; init?: RequestInit }[] = []
  let invalidations = 0
  const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
  const api = createApiClient({ baseUrl: '/api/v1/', origin: 'http://127.0.0.1:5173', onProgressScopeInvalidated: () => { invalidations++ },
    fetch: async (input, init) => {
      const url = String(input); calls.push({ url, init })
      if (url.endsWith('/auth/csrf/')) return response({ data: { csrf_token: 'synthetic' } })
      if (url.includes('/reading/')) return response({ data: toc() })
      if (url.endsWith('/read/')) return response({ error: { code: 'progress_reset', message: 'Safe refusal' } }, 409)
      throw new Error('A fresh generation must not be substituted')
    } })
  await api.learning.reading('12')
  await assert.rejects(api.progress.markSectionRead('12', '101', '1'), error => error instanceof ApiError && error.code === 'progress_reset')
  const post = calls.find(c => c.init?.method === 'POST')!
  assert.equal(new Headers(post.init?.headers).get('X-Progress-Generation'), '1')
  assert.equal(calls.some(c => c.url.includes('/completion-progress/')), false)
  assert.equal(invalidations, 1)
})
