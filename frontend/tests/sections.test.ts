import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createApiClient, ApiError } from '../src/api/client.ts'
import { sectionsArticle, ContractError } from '../src/api/decoders.ts'
import { learningDestination, sectionFromHash } from '../src/learning/routing.ts'

const article = {
  topic_id: '12', title: 'Тема', language: 'ru', sections: [
    { section_id: '101', position: 10, title: 'Первый', article_body: '  Текст\r\n\n' },
    { section_id: '105', position: 30, title: 'Второй', article_body: '<script>not executed</script>' },
  ],
}

test('sections decoder preserves order and verbatim plain text without adding legacy fields', () => {
  assert.deepEqual(sectionsArticle(article), article)
  assert.deepEqual(Object.keys(sectionsArticle(article)), ['topic_id', 'title', 'language', 'sections'])
})

for (const language of ['ru', 'en'] as const) {
  test(`sections GET uses the exact URL, material ${language} and included session, without a write`, async () => {
    const calls: { url: string; init: RequestInit | undefined }[] = []
    const api = createApiClient({ baseUrl: '/api/v1/', origin: 'http://127.0.0.1:5173', fetch: async (input, init) => {
      calls.push({ url: String(input), init })
      return new Response(JSON.stringify({ data: { ...article, language } }), { headers: { 'Content-Type': 'application/json' } })
    } })
    assert.equal((await api.learning.sections('12', language)).language, language)
    assert.equal(calls.length, 1)
    assert.equal(calls[0].url, `http://127.0.0.1:5173/api/v1/topics/12/sections/?language=${language}`)
    assert.equal(calls[0].init?.method ?? 'GET', 'GET')
    assert.equal(calls[0].init?.credentials, 'include')
    assert.equal(calls[0].init?.body, undefined)
    assert.equal(new Headers(calls[0].init?.headers).has('X-CSRFToken'), false)
  })
}

for (const field of ['revision', 'status', 'expected_answer', 'snapshot', 'server_key', 'is_correct']) {
  test(`sections decoder rejects internal field ${field} at both levels`, () => {
    assert.throws(() => sectionsArticle({ ...article, [field]: 'synthetic-private-value' }), ContractError)
    assert.throws(() => sectionsArticle({ ...article, sections: [{ ...article.sections[0], [field]: 'synthetic-private-value' }] }), ContractError)
  })
}

test('partial or unordered sections cannot become a successfully rendered article', () => {
  for (const invalid of [
    { ...article, sections: [] }, { ...article, language: 'de' },
    { ...article, sections: [...article.sections].reverse() },
    { ...article, sections: [article.sections[0], { ...article.sections[1], position: 10 }] },
    { ...article, sections: [article.sections[0], { ...article.sections[1], section_id: '101' }] },
    ...[{ position: 0 }, { position: 1.2 }, { section_id: '0' }, { section_id: '//outside.invalid' },
      { title: '  ' }, { article_body: '' }, { article_body: null }].map(change => ({ ...article, sections: [{ ...article.sections[0], ...change }] })),
  ]) assert.throws(() => sectionsArticle(invalid), ContractError)
})

test('section anchors are internal, keep the material language and ignore unsafe hashes', () => {
  assert.equal(sectionFromHash('#section-105'), '105')
  assert.equal(learningDestination({ topicId: '12', language: 'en' }, '105'), '/topics/12?language=en#section-105')
  assert.equal(learningDestination({ topicId: '12', language: 'ru' }, '101'), '/topics/12#section-101')
  for (const hash of ['', '#section-0', '#section--1', '#section-1/elsewhere', '#https://outside.invalid', '#section-1?next=outside']) {
    assert.equal(sectionFromHash(hash), null)
    assert.equal(learningDestination({ topicId: '12', language: 'en' }, hash), '/topics/12?language=en')
  }
  assert.equal(learningDestination({ topicId: null, language: 'ru' }, '101'), '/topics')
})

for (const [status, code] of [[400, 'validation_error'], [403, 'authentication_required'], [404, 'not_found']] as const) {
  test(`sections ${status} uses the shared ApiError contract`, async () => {
    const api = createApiClient({ baseUrl: '/api/v1/', origin: 'http://127.0.0.1:5173', fetch: async () =>
      new Response(JSON.stringify({ error: { code, message: 'Safe failure.' } }), { status, headers: { 'Content-Type': 'application/json' } }) })
    await assert.rejects(api.learning.sections('12', 'ru'), error => error instanceof ApiError && error.status === status && error.code === code)
  })
}
