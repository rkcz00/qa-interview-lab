import * as decode from './decoders.ts'
import type { Decoder } from './decoders.ts'
import type { Answer, ErrorFields, Language } from './types.ts'

type ErrorKind = 'http' | 'network' | 'protocol' | 'configuration'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly kind: ErrorKind
  readonly fields?: ErrorFields

  constructor(options: { status: number; code: string; message: string; kind: ErrorKind; fields?: ErrorFields }) {
    super(options.message)
    this.name = 'ApiError'
    this.status = options.status
    this.code = options.code
    this.kind = options.kind
    this.fields = options.fields
  }
}

export interface ApiClientOptions {
  baseUrl: string
  origin: string
  fetch?: typeof globalThis.fetch
  timeoutMs?: number
}

function configurationError(): never {
  throw new ApiError({
    status: 0, code: 'invalid_configuration', kind: 'configuration', message: 'Некорректная настройка API-клиента.',
  })
}

function resolveBaseUrl(options: ApiClientOptions) {
  try {
    const origin = new URL(options.origin)
    const base = new URL(options.baseUrl, origin.origin + '/')
    if (!options.baseUrl || !['http:', 'https:'].includes(base.protocol) || base.origin !== origin.origin ||
        base.username || base.password || base.search || base.hash) return configurationError()
    if (!base.pathname.endsWith('/')) base.pathname += '/'
    return base
  } catch {
    return configurationError()
  }
}

function invalidResponse(status: number) {
  return new ApiError({
    status, code: 'invalid_response', kind: 'protocol', message: 'Сервер вернул ответ неожиданного формата.',
  })
}

function pathId(id: string) {
  if (!id || id === '.' || id === '..') return configurationError()
  return encodeURIComponent(id)
}

function localized(path: string, language?: Language) {
  return path + (language === undefined ? '' : '?' + new URLSearchParams({ language }).toString())
}

export function createApiClient(options: ApiClientOptions) {
  const base = resolveBaseUrl(options)
  const fetchRequest = options.fetch ?? globalThis.fetch.bind(globalThis)
  const timeoutMs = options.timeoutMs ?? 15_000
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 2_147_483_647) configurationError()

  async function request<T>(path: string, expectedStatus: number, decoder: Decoder<T>, body?: string, token?: string): Promise<T> {
    const headers: Record<string, string> = { Accept: 'application/json' }
    if (body !== undefined) {
      if (token === undefined) configurationError()
      headers['Content-Type'] = 'application/json'
      headers['X-CSRFToken'] = token
    }
    let response: Response
    try {
      response = await fetchRequest(new URL(path, base).href, {
        method: body === undefined ? 'GET' : 'POST', credentials: 'include', headers, body,
        cache: 'no-store', redirect: 'error', signal: AbortSignal.timeout(timeoutMs),
      })
    } catch {
      throw new ApiError({ status: 0, code: 'network_error', kind: 'network', message: 'Не удалось получить ответ сервера.' })
    }
    if (response.status === 204 && expectedStatus === 204) return decoder(undefined)
    if (response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase() !== 'application/json') {
      throw invalidResponse(response.status)
    }
    let payload: unknown
    try {
      payload = JSON.parse(await response.text())
    } catch {
      throw invalidResponse(response.status)
    }
    try {
      if (!response.ok) {
        const { error } = decode.errorEnvelope(payload)
        throw new ApiError({ ...error, status: response.status, kind: 'http' })
      }
      if (response.status !== expectedStatus) throw invalidResponse(response.status)
      return decode.dataOf(payload, decoder)
    } catch (error) {
      if (error instanceof decode.ContractError) throw invalidResponse(response.status)
      throw error
    }
  }

  // Only an in-flight promise holds the token. A fresh bootstrap precedes every POST,
  // including the first request after Django rotates its CSRF secret during login.
  let csrfFlight: Promise<string> | undefined
  function csrf() {
    csrfFlight ??= request('auth/csrf/', 200, decode.csrfToken).finally(() => { csrfFlight = undefined })
    return csrfFlight
  }

  async function post<T>(path: string, body: unknown, expectedStatus: number, decoder: Decoder<T>) {
    const serialized = JSON.stringify(body)
    const token = await csrf()
    return request(path, expectedStatus, decoder, serialized, token)
  }

  return {
    auth: {
      bootstrap: async (): Promise<void> => { await csrf() },
      register: (email: string, password: string) => post('auth/register/', { email, password }, 201, decode.account),
      login: (email: string, password: string) => post('auth/login/', { email, password }, 200, decode.account),
      logout: () => post('auth/logout/', {}, 204, () => undefined),
      currentSession: () => request('auth/me/', 200, decode.account),
    },
    learning: {
      catalog: (language?: Language) => request(localized('topics/', language), 200, decode.arrayOf(decode.topicSummary)),
      article: (topicId: string, language?: Language) => request(localized(`topics/${pathId(topicId)}/`, language), 200, decode.article),
      terms: (topicId: string, language?: Language) => request(localized(`topics/${pathId(topicId)}/terms/`, language), 200, decode.arrayOf(decode.term)),
    },
    assessment: {
      start: (topicId: string, language: Language) => post(`topics/${pathId(topicId)}/attempts/`, { language }, 201, decode.pendingAttempt),
      get: (attemptId: string, language?: Language) => request(localized(`attempts/${pathId(attemptId)}/`, language), 200, decode.attempt),
      submit: (attemptId: string, language: Language, answers: readonly Answer[]) => post(
        `attempts/${pathId(attemptId)}/submit/`,
        { language, answers: answers.map(answer => ({ question_id: answer.question_id, choice_ids: [...answer.choice_ids] })) },
        200, decode.submittedAttempt,
      ),
      history: () => request('attempts/', 200, decode.arrayOf(decode.submittedAttempt)),
    },
    progress: {
      markRead: (topicId: string) => post(`topics/${pathId(topicId)}/read/`, {}, 200, decode.progress),
      current: () => request('progress/', 200, decode.arrayOf(decode.progress)),
    },
  }
}

export type ApiClient = ReturnType<typeof createApiClient>
