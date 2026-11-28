import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ApiError } from '../src/api/client.ts'
import type { LearningApi } from '../src/learning/model.ts'
import type { SectionArticle, SectionRead, TopicReading } from '../src/api/types.ts'
import { SectionReads } from '../src/learning/reading.ts'
import type { LearningLocation } from '../src/learning/routing.ts'
import type { Destination } from '../src/auth/routing.ts'
import { resolveRoute } from '../src/auth/routing.ts'
import { LearningStore, learningFailure } from '../src/learning/model.ts'
import { authDestination, learningDestination, learningLocation } from '../src/learning/routing.ts'

const article: SectionArticle = { topic_id: '12', topic_title: 'Тестирование', section: { section_id: '101', position: 10, title: 'Раздел', article_body: '<script>untrusted()</script>', read_at: null }, language: 'ru', progress_generation: '1', previous_section_id: null, next_section_id: null,
  reading: { total_sections: 1, read_sections: 0, is_read: false, completion_contribution: 0 } }
const terms = [
  { term_id: '2', position: 10, language: 'ru' as const, name: 'Первый', definition: 'Определение' },
  { term_id: '10', position: 10, language: 'ru' as const, name: 'Второй', definition: 'Определение' },
]
const progress: SectionRead = { topic_id: '12', section_id: '101', read_at: '2026-11-12T10:00:00Z', progress_generation: '1',
  reading: { total_sections: 1, read_sections: 1, is_read: true, completion_contribution: 30 } }
function reading(at: string | null = null): TopicReading {
  return { topic_id: '12', title: article.topic_title, language: 'ru', progress_generation: '1',
    reading: { total_sections: 1, read_sections: at ? 1 : 0, is_read: at !== null, completion_contribution: at ? 30 : 0 },
    sections: [{ section_id: '101', position: 10, title: 'Раздел', read_at: at }] }
}
function ready(at: string | null, pending: boolean, retry = false) {
  return { kind: 'ready', complete: at !== null, reading: reading(at).reading, pending, sections: { '101': at }, ...(retry ? { retryRequired: true } : {}) }
}
const failure = (status: number, code: string) => new ApiError({ status, code, kind: status ? 'http' : 'network', message: 'Untrusted details' })
function mockApi() {
  const calls: string[] = []
  const api: LearningApi = {
    learning: {
      catalog: async language => { calls.push('catalog:' + language); return [{ topic_id: '2', title: 'Второй' }, { topic_id: '10', title: 'Десятый' }] },
      section: async (id, _sectionId, language) => { calls.push(`article:${id}:${language}`); return article },
      terms: async (id, language) => { calls.push(`terms:${id}:${language}`); return terms },
      reading: async (_id, language = 'ru') => { calls.push('reading'); return { ...reading(), language } },
    },
    progress: {
      markSectionRead: async id => { calls.push('read:' + id); return progress },
    },
  }
  return { api, calls }
}
function makeStore(api: LearningApi, location: LearningLocation) {
  const reads = new SectionReads(api); reads.bindOwner('learner-1')
  return new LearningStore(api, location, reads)
}
const tick = async () => { await new Promise<void>(resolve => setTimeout(resolve, 0)) }

test('Learning locations default to RU and use only the material language', () => {
  assert.deepEqual(learningLocation('/topics', ''), { topicId: null, sectionId: null, language: 'ru' })
  assert.deepEqual(learningLocation('/topics/12', '?language=en'), { topicId: '12', sectionId: null, language: 'en' })
  assert.equal(learningDestination({ topicId: '12', sectionId: '101', language: 'en' }), '/topics/12/sections/101?language=en')
  assert.equal(learningDestination({ topicId: '12', sectionId: '101', language: 'ru' }), '/topics/12/sections/101')
  assert.deepEqual(learningLocation('/topics/12', '?next=https://outside.invalid&returnTo=/register'), { topicId: '12', sectionId: null, language: 'ru' })
  for (const search of ['?language=de', '?language=', '?language=ru&language=en']) assert.equal(learningLocation('/topics/12', search), null)
})

test('router and login return targets reject external or malformed paths', () => {
  for (const path of ['/topics/12/terms', '/topics/', '//outside.invalid', '/topics/12?language=en']) assert.equal(resolveRoute(path), null)
  for (const route of ['/topics/%2Foutside', '/topics/%2e%2e', '/topics/%ZZ', '/topics/a%5Cb'] as const) assert.equal(learningLocation(route, ''), null)
  assert.equal(authDestination(undefined), '/')
  assert.equal(authDestination('/topics/12?language=en'), '/')
  for (const path of ['https://outside.invalid', '//outside.invalid', '/login', '/topics/12/elsewhere', '/topics/%2foutside']) {
    assert.equal(authDestination(path as Destination), '/')
  }
})

test('catalog preserves API order and performs no progress or write request', async () => {
  const { api, calls } = mockApi()
  const store = makeStore(api, { topicId: null, sectionId: null, language: 'en' })
  await store.load()
  const content = store.getSnapshot().content
  assert.equal(content.kind, 'catalog')
  if (content.kind === 'catalog') assert.deepEqual(content.topics.map(topic => topic.topic_id), ['2', '10'])
  assert.deepEqual(calls, ['catalog:en'])
})

test('selected article, contents and read state load without changing progress or interpreting text', async () => {
  const { api, calls } = mockApi()
  const store = makeStore(api, { topicId: '12', sectionId: '101', language: 'ru' })
  await store.load()
  await tick()
  assert.deepEqual(store.getSnapshot().content, { kind: 'topic', topic: reading(), article, terms })
  assert.deepEqual(store.getSnapshot().read, ready(null, false))
  assert.deepEqual(new Set(calls), new Set(['reading', 'article:12:ru', 'terms:12:ru']))
})

test('empty catalog is a successful state', async () => {
  const { api } = mockApi()
  api.learning.catalog = async () => []
  const store = makeStore(api, { topicId: null, sectionId: null, language: 'ru' })
  await store.load()
  assert.deepEqual(store.getSnapshot().content, { kind: 'catalog', topics: [] })
})

test('one Learning store switches translations, ignores old responses and preserves the shared read mark', async () => {
  const { api, calls } = mockApi()
  let finishOld!: (value: typeof article) => void
  api.learning.section = async (_id, _sectionId, language) => language === 'ru'
    ? new Promise(resolve => { finishOld = resolve }) : { ...article, language: 'en' }
  api.learning.terms = async (_id, language = 'ru') => terms.map(term => ({ ...term, language }))
  api.learning.reading = async (_id, language = 'ru') => ({ ...reading(progress.read_at), language })
  const store = makeStore(api, { topicId: '12', sectionId: '101', language: 'ru' })
  const old = store.load()
  await store.load({ topicId: '12', sectionId: '101', language: 'en' })
  finishOld(article)
  await old
  await tick()
  const state = store.getSnapshot()
  assert.equal(state.content.kind, 'topic')
  if (state.content.kind === 'topic') {
    assert.equal(state.content.article?.language, 'en')
    assert.equal(state.content.topic.language, 'en')
    assert.equal(state.content.terms[0].language, 'en')
  }
  assert.deepEqual(state.read, ready(progress.read_at, false))
  await store.markRead()
  assert.equal(calls.some(call => call.startsWith('read:')), false)
})

for (const [status, code, kind] of [[404, 'not_found', 'not_found'], [403, 'authentication_required', 'authentication'], [0, 'network_error', 'error'], [500, 'internal_error', 'error']] as const) {
  test(`content error ${code} clears public data and uses a safe state`, async () => {
    const { api } = mockApi()
    api.learning.section = async () => { throw failure(status, code) }
    const store = makeStore(api, { topicId: '12', sectionId: '101', language: 'ru' })
    await store.load()
    await tick()
    const content = store.getSnapshot().content
    assert.equal(content.kind, kind)
    assert.equal(JSON.stringify(content).includes('Untrusted details'), false)
  })
}

test('failed contents metadata prevents a partial reader and writes until a successful reload GET', async () => {
  const { api, calls } = mockApi()
  api.learning.reading = async () => { throw failure(500, 'internal_error') }
  const store = makeStore(api, { topicId: '12', sectionId: '101', language: 'ru' })
  await store.load()
  await tick()
  assert.equal(store.getSnapshot().content.kind, 'error')
  assert.equal(store.getSnapshot().read.kind, 'loading')
  await store.markRead()
  assert.equal(calls.includes('read:12'), false)
  api.learning.reading = async () => reading()
  await store.load()
  assert.deepEqual(store.getSnapshot().read, ready(null, false))
})

test('only explicit mark writes; double click and an existing mark do not write again', async () => {
  const { api, calls } = mockApi()
  let complete!: (value: SectionRead) => void
  api.progress.markSectionRead = async id => {
    calls.push('read:' + id)
    return new Promise<SectionRead>(resolve => { complete = resolve })
  }
  const store = makeStore(api, { topicId: '12', sectionId: '101', language: 'ru' })
  await store.load()
  const writing = store.markRead()
  await store.markRead()
  assert.deepEqual(store.getSnapshot().read, ready(null, true))
  complete(progress)
  await writing
  await store.markRead()
  assert.equal(calls.filter(call => call === 'read:12').length, 1)
  assert.deepEqual(store.getSnapshot().read, ready(progress.read_at, false))
})

test('language changes and concurrent read triggers share one pending POST and its first date', async () => {
  const { api, calls } = mockApi()
  let complete!: (value: SectionRead) => void
  api.learning.section = async (_id, _sectionId, language = 'ru') => ({ ...article, language })
  api.learning.terms = async (_id, language = 'ru') => terms.map(term => ({ ...term, language }))
  api.progress.markSectionRead = async id => {
    calls.push('read:' + id)
    return new Promise<SectionRead>(resolve => { complete = resolve })
  }
  const store = makeStore(api, { topicId: '12', sectionId: '101', language: 'ru' })
  await store.load()
  const writing = store.markRead()
  for (const language of ['en', 'ru', 'en'] as const) {
    await store.load({ topicId: '12', sectionId: '101', language })
    await store.refreshRead()
    assert.deepEqual(store.getSnapshot().read, ready(null, true))
    await Promise.all([store.markRead(), store.markRead(), store.markRead()])
  }
  assert.equal(calls.filter(call => call === 'read:12').length, 1)
  complete(progress)
  await writing
  for (const language of ['ru', 'en'] as const) {
    await store.load({ topicId: '12', sectionId: '101', language })
    await store.markRead()
    assert.deepEqual(store.getSnapshot().read, ready(progress.read_at, false))
  }
  assert.equal(calls.filter(call => call === 'read:12').length, 1)
})

test('failed read across a language change requires an explicit check before retrying', async () => {
  const { api, calls } = mockApi()
  let reject!: (reason: unknown) => void
  api.learning.section = async (_id, _sectionId, language = 'ru') => ({ ...article, language })
  api.learning.terms = async (_id, language = 'ru') => terms.map(term => ({ ...term, language }))
  api.progress.markSectionRead = async id => {
    calls.push('read:' + id)
    return new Promise<SectionRead>((_resolve, fail) => { reject = fail })
  }
  const store = makeStore(api, { topicId: '12', sectionId: '101', language: 'ru' })
  await store.load()
  const writing = store.markRead()
  await store.load({ topicId: '12', sectionId: '101', language: 'en' })
  reject(failure(0, 'network_error'))
  await writing
  assert.equal(store.getSnapshot().read.kind, 'error')
  await store.load({ topicId: '12', sectionId: '101', language: 'ru' })
  await store.markRead()
  assert.equal(store.getSnapshot().read.kind, 'error')
  assert.equal(calls.filter(call => call === 'read:12').length, 1)
  await store.refreshRead()
  assert.deepEqual(store.getSnapshot().read, ready(null, false, true))
  store.allowRetry()
  api.progress.markSectionRead = async id => { calls.push('read:' + id); return progress }
  await store.markRead()
  assert.deepEqual(store.getSnapshot().read, ready(progress.read_at, false))
  assert.equal(calls.filter(call => call === 'read:12').length, 2)
})

for (const initialLanguage of ['ru', 'en'] as const) {
  for (const loadOutcome of ['success', 'article_network_error', 'reading_server_error'] as const) {
    for (const completeBeforeRetry of [false, true]) {
      test(`${initialLanguage}: pending read survives ${loadOutcome}; response ${completeBeforeRetry ? 'before' : 'after'} content retry`, async () => {
        const { api, calls } = mockApi()
        let rejectTranslation = false
        let complete!: (value: SectionRead) => void
        api.learning.section = async (_id, _sectionId, language = 'ru') => {
          if (rejectTranslation && loadOutcome === 'article_network_error') throw failure(0, 'network_error')
          return { ...article, language }
        }
        api.learning.terms = async (_id, language = 'ru') => terms.map(term => ({ ...term, language }))
        api.learning.reading = async (_id, language = 'ru') => {
          calls.push('reading')
          if (rejectTranslation && loadOutcome === 'reading_server_error') throw failure(500, 'internal_error')
          return { ...reading(), language }
        }
        api.progress.markSectionRead = async id => {
          calls.push('read:' + id)
          return new Promise<SectionRead>(resolve => { complete = resolve })
        }
        const store = makeStore(api, { topicId: '12', sectionId: '101', language: initialLanguage })
        await store.load()
        const writing = store.markRead()
        rejectTranslation = true
        await store.load({ topicId: '12', sectionId: '101', language: initialLanguage === 'ru' ? 'en' : 'ru' })
        assert.equal(store.getSnapshot().content.kind, loadOutcome === 'success' ? 'topic' : 'error')
        assert.deepEqual(store.getSnapshot().read, ready(null, true))
        await store.refreshRead()
        assert.equal(calls.filter(call => call === 'reading').length, 2)
        if (completeBeforeRetry) {
          complete(progress)
          await writing
          assert.deepEqual(store.getSnapshot().read, ready(progress.read_at, false))
        }
        rejectTranslation = false
        await store.load()
        if (!completeBeforeRetry) assert.deepEqual(store.getSnapshot().read, ready(null, true))
        await Promise.all([store.markRead(), store.markRead()])
        assert.equal(calls.filter(call => call === 'read:12').length, 1)
        if (!completeBeforeRetry) {
          complete(progress)
          await writing
        }
        for (const language of ['ru', 'en'] as const) {
          await store.load({ topicId: '12', sectionId: '101', language })
          await store.markRead()
          assert.deepEqual(store.getSnapshot().read, ready(progress.read_at, false))
        }
        assert.equal(calls.filter(call => call === 'read:12').length, 1)
      })
    }
  }

  test(`${initialLanguage}: failed read stays failed across translation errors until an explicit progress GET`, async () => {
    const { api, calls } = mockApi()
    let rejectTranslation = false
    let reject!: (reason: unknown) => void
    api.learning.section = async (_id, _sectionId, language = 'ru') => {
      if (rejectTranslation) throw failure(0, 'network_error')
      return { ...article, language }
    }
    api.learning.terms = async (_id, language = 'ru') => terms.map(term => ({ ...term, language }))
    api.progress.markSectionRead = async id => {
      calls.push('read:' + id)
      return new Promise<SectionRead>((_resolve, fail) => { reject = fail })
    }
    const store = makeStore(api, { topicId: '12', sectionId: '101', language: initialLanguage })
    await store.load()
    const writing = store.markRead()
    rejectTranslation = true
    await store.load({ topicId: '12', sectionId: '101', language: initialLanguage === 'ru' ? 'en' : 'ru' })
    reject(failure(0, 'network_error'))
    await writing
    assert.equal(store.getSnapshot().read.kind, 'error')
    rejectTranslation = false
    await store.load()
    await store.markRead()
    assert.equal(store.getSnapshot().read.kind, 'error')
    assert.equal(calls.filter(call => call === 'read:12').length, 1)
    assert.equal(calls.filter(call => call === 'reading').length, 3)
    await store.refreshRead()
    store.allowRetry()
    api.progress.markSectionRead = async id => { calls.push('read:' + id); return progress }
    await store.markRead()
    assert.equal(calls.filter(call => call === 'reading').length, 4)
    assert.equal(calls.filter(call => call === 'read:12').length, 2)
    assert.deepEqual(store.getSnapshot().read, ready(progress.read_at, false))
  })
}

test('a lost session during translation loading still invalidates a late read response', async () => {
  const { api } = mockApi()
  let complete!: (value: SectionRead) => void
  api.progress.markSectionRead = () => new Promise<SectionRead>(resolve => { complete = resolve })
  const store = makeStore(api, { topicId: '12', sectionId: '101', language: 'ru' })
  await store.load()
  const writing = store.markRead()
  api.learning.section = async () => { throw failure(403, 'authentication_required') }
  await store.load({ topicId: '12', sectionId: '101', language: 'en' })
  const expired = store.getSnapshot()
  assert.equal(expired.content.kind, 'authentication')
  assert.deepEqual(expired.read, { kind: 'loading' })
  complete(progress)
  await writing
  assert.deepEqual(store.getSnapshot(), expired)
})

test('a shared read mark survives loading the other material language', async () => {
  const { api } = mockApi()
  api.learning.reading = async (_id, language = 'ru') => ({ ...reading(progress.read_at), language })
  api.learning.section = async () => ({ ...article, language: 'en' })
  api.learning.terms = async () => terms.map(term => ({ ...term, language: 'en' }))
  const store = makeStore(api, { topicId: '12', sectionId: '101', language: 'en' })
  await store.load()
  assert.deepEqual(store.getSnapshot().read, ready(progress.read_at, false))
})

test('interrupted read POST is not replayed and a GET can confirm the saved mark', async () => {
  const { api, calls } = mockApi()
  api.progress.markSectionRead = async () => { calls.push('write'); throw failure(0, 'network_error') }
  const store = makeStore(api, { topicId: '12', sectionId: '101', language: 'ru' })
  await store.load()
  await store.markRead()
  await store.markRead()
  assert.equal(store.getSnapshot().read.kind, 'error')
  assert.deepEqual(calls.filter(call => call === 'write'), ['write'])
  api.learning.reading = async (_id, language = 'ru') => ({ ...reading(progress.read_at), language })
  await store.refreshRead()
  assert.deepEqual(store.getSnapshot().read, ready(progress.read_at, false))
})

test('a topic becoming unavailable on read POST clears its content', async () => {
  const { api } = mockApi()
  api.progress.markSectionRead = async () => { throw failure(404, 'not_found') }
  const store = makeStore(api, { topicId: '12', sectionId: '101', language: 'ru' })
  await store.load()
  await store.markRead()
  assert.deepEqual(store.getSnapshot().content, { kind: 'not_found' })
})

test('late content and progress cannot overwrite a lost session', async () => {
  const { api } = mockApi()
  let articleReady!: (value: typeof article) => void
  api.learning.section = () => new Promise(resolve => { articleReady = resolve })
  api.learning.reading = async () => { throw failure(403, 'authentication_required') }
  const store = makeStore(api, { topicId: '12', sectionId: '101', language: 'ru' })
  const loading = store.load()
  await tick()
  articleReady(article)
  await loading
  assert.deepEqual(store.getSnapshot().content, { kind: 'authentication' })
})

test('unmount invalidates pending reads without publishing old content', async () => {
  const { api } = mockApi()
  let finish!: (value: typeof article) => void
  api.learning.section = () => new Promise(resolve => { finish = resolve })
  const store = makeStore(api, { topicId: '12', sectionId: '101', language: 'ru' })
  const loading = store.load()
  store.invalidate()
  finish(article)
  await loading
  assert.equal(store.getSnapshot().content.kind, 'loading')
})

test('a response for a different topic or language is never rendered', async () => {
  const { api } = mockApi()
  api.learning.section = async () => ({ ...article, topic_id: 'other' })
  const store = makeStore(api, { topicId: '12', sectionId: '101', language: 'ru' })
  await store.load()
  assert.equal(store.getSnapshot().content.kind, 'error')
})

test('error classification uses the existing ApiError and does not expose details', () => {
  assert.equal(learningFailure(new Error('Internal detail')), 'server')
  assert.equal(learningFailure(failure(403, 'csrf_failed')), 'csrf')
  assert.equal(learningFailure(failure(500, 'authentication_required')), 'server')
})
