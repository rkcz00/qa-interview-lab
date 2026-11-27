import * as decode from './decoders.ts'
import type { Decoder } from './decoders.ts'
import type { Answer, CompletionProgress, ErrorFields, Language } from './types.ts'

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
  onProgressReset?: (reason: 'reset' | 'session') => void
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

  let progressEpoch = 0
  let progressGeneration: string | undefined
  let generationFlight: Promise<string> | undefined
  let progressBlocked = false
  let sessionUserId: string | undefined
  let channel: BroadcastChannel | undefined
  function resetError() {
    return new ApiError({ status: 409, code: 'progress_reset', kind: 'http', message: 'Прогресс сброшен. Откройте материал заново.' })
  }
  function invalidateProgress(block = false, reason: 'reset' | 'session' = 'reset') {
    const wasBlocked = progressBlocked
    progressEpoch++
    progressGeneration = undefined
    generationFlight = undefined
    progressBlocked = block
    if (block && (!wasBlocked || reason === 'session')) options.onProgressReset?.(reason)
  }
  function progressChannel() {
    if (channel || typeof window === 'undefined' || typeof window.BroadcastChannel !== 'function') return
    channel = new window.BroadcastChannel('qil-progress-state')
    channel.addEventListener('message', event => {
      if (event.data === 'progress-reset' || event.data === 'session-changed') {
        invalidateProgress(true, event.data === 'session-changed' ? 'session' : 'reset')
      }
    })
    window.addEventListener('pagehide', () => { channel?.close(); channel = undefined }, { once: true })
  }
  function signalReset() {
    progressChannel()
    channel?.postMessage('progress-reset')
    invalidateProgress(true)
  }

  async function request<T>(path: string, expectedStatus: number, decoder: Decoder<T>, body?: string, token?: string,
    generation?: string, epoch?: number): Promise<T> {
    const headers: Record<string, string> = { Accept: 'application/json' }
    if (body !== undefined) {
      if (token === undefined) configurationError()
      headers['Content-Type'] = 'application/json'
      headers['X-CSRFToken'] = token
      if (generation !== undefined) headers['X-Progress-Generation'] = generation
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
    if (epoch !== undefined && epoch !== progressEpoch) throw resetError()
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
    if (epoch !== undefined && epoch !== progressEpoch) throw resetError()
    try {
      if (!response.ok) {
        const { error } = decode.errorEnvelope(payload)
        if (error.code === 'progress_reset') signalReset()
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

  async function completion(): Promise<CompletionProgress> {
    progressChannel()
    const value = await request('completion-progress/', 200, decode.completionProgress, undefined, undefined, undefined, progressEpoch)
    if (progressGeneration !== undefined && BigInt(value.progress_generation) < BigInt(progressGeneration)) throw resetError()
    progressGeneration = value.progress_generation
    progressBlocked = false
    return value
  }

  function generation(): Promise<string> {
    if (progressBlocked) return Promise.reject(resetError())
    progressChannel()
    if (progressGeneration !== undefined) return Promise.resolve(progressGeneration)
    const epoch = progressEpoch
    generationFlight ??= completion().then(value => value.progress_generation).finally(() => {
      if (epoch === progressEpoch) generationFlight = undefined
    })
    return generationFlight
  }

  async function post<T>(path: string, body: unknown, expectedStatus: number, decoder: Decoder<T>, progressWrite = false, explicitGeneration?: string) {
    const epoch = progressEpoch
    const serialized = JSON.stringify(body)
    const token = await csrf()
    let currentGeneration: string | undefined
    if (progressWrite) {
      if (explicitGeneration === undefined) currentGeneration = await generation()
      else {
        try { currentGeneration = decode.progressGeneration(explicitGeneration) }
        catch { configurationError() }
      }
      if (epoch !== progressEpoch) throw resetError()
    }
    return request(path, expectedStatus, decoder, serialized, token, currentGeneration, progressWrite ? epoch : undefined)
  }

  async function authPost<T>(path: string, body: unknown, status: number, decoder: Decoder<T>) {
    invalidateProgress()
    sessionUserId = undefined
    const result = await post(path, body, status, decoder)
    progressChannel()
    channel?.postMessage('session-changed')
    return result
  }

  return {
    auth: {
      bootstrap: async (): Promise<void> => { await csrf() },
      register: (email: string, password: string) => authPost('auth/register/', { email, password }, 201, decode.account),
      login: (email: string, password: string) => authPost('auth/login/', { email, password }, 200, decode.account),
      logout: () => authPost('auth/logout/', {}, 204, () => undefined),
      currentSession: async () => {
        try {
          const account = await request('auth/me/', 200, decode.account)
          if (sessionUserId !== undefined && sessionUserId !== account.user_id) invalidateProgress()
          sessionUserId = account.user_id
          return account
        } catch (error) {
          if (error instanceof ApiError && error.code === 'authentication_required') { invalidateProgress(); sessionUserId = undefined }
          throw error
        }
      },
    },
    learning: {
      catalog: (language?: Language) => request(localized('topics/', language), 200, decode.arrayOf(decode.topicSummary)),
      article: (topicId: string, language?: Language) => request(localized(`topics/${pathId(topicId)}/`, language), 200, decode.article),
      sections: (topicId: string, language?: Language) => request(localized(`topics/${pathId(topicId)}/sections/`, language), 200, decode.sectionsArticle),
      reading: (topicId: string, language?: Language) => request(localized(`topics/${pathId(topicId)}/reading/`, language), 200, decode.topicReading, undefined, undefined, undefined, progressEpoch),
      section: (topicId: string, sectionId: string, language?: Language) => request(localized(`topics/${pathId(topicId)}/sections/${pathId(sectionId)}/`, language), 200, decode.sectionArticle, undefined, undefined, undefined, progressEpoch),
      terms: (topicId: string, language?: Language) => request(localized(`topics/${pathId(topicId)}/terms/`, language), 200, decode.arrayOf(decode.term)),
    },
    assessment: {
      start: (topicId: string, language: Language) => post(`topics/${pathId(topicId)}/attempts/`, { language }, 201, decode.pendingAttempt, true),
      get: (attemptId: string, language?: Language) => request(localized(`attempts/${pathId(attemptId)}/`, language), 200, decode.attempt, undefined, undefined, undefined, progressEpoch),
      submit: (attemptId: string, language: Language, answers: readonly Answer[]) => post(
        `attempts/${pathId(attemptId)}/submit/`,
        { language, answers: answers.map(answer => ({ question_id: answer.question_id, choice_ids: [...answer.choice_ids] })) },
        200, decode.submittedAttempt, true,
      ),
      history: () => request('attempts/', 200, decode.arrayOf(decode.submittedAttempt), undefined, undefined, undefined, progressEpoch),
    },
    progress: {
      markSectionRead: (topicId: string, sectionId: string) => post(`topics/${pathId(topicId)}/sections/${pathId(sectionId)}/read/`, {}, 200, decode.sectionRead, true),
      markRead: (topicId: string) => post(`topics/${pathId(topicId)}/read/`, {}, 200, decode.progress, true),
      current: async () => {
        const epoch = progressEpoch
        await generation()
        if (epoch !== progressEpoch) throw resetError()
        return request('progress/', 200, decode.arrayOf(decode.progress), undefined, undefined, undefined, epoch)
      },
      completion,
      reset: async (confirmation: 'reset_all_progress', requestId: string, expectedGeneration: string) => {
        try {
          const result = await post('progress/reset/', { confirmation, request_id: requestId }, 200, decode.resetProgress, true, expectedGeneration)
          signalReset()
          return result
        } catch (error) {
          if (error instanceof ApiError && (error.kind === 'network' || error.kind === 'protocol')) signalReset()
          throw error
        }
      },
    },
    practice: {
      preview: (topicId: string, language?: Language) => request(localized(`topics/${pathId(topicId)}/practice/`, language), 200, decode.practicePreview),
      start: (topicId: string, language: Language) => post(`topics/${pathId(topicId)}/practice/submissions/`, { language }, 201, decode.pendingPractice, true),
      get: (submissionId: string, language?: Language) => request(localized(`practice-submissions/${pathId(submissionId)}/`, language), 200, decode.practiceSubmission, undefined, undefined, undefined, progressEpoch),
      submit: (submissionId: string, language: Language, answerText: string) => post(`practice-submissions/${pathId(submissionId)}/submit/`, { language, answer_text: answerText }, 200, decode.submittedPractice, true),
      delete: (submissionId: string): Promise<void> => post(`practice-submissions/${pathId(submissionId)}/delete/`, {}, 204, () => undefined, true),
    },
  }
}

export type ApiClient = ReturnType<typeof createApiClient>
