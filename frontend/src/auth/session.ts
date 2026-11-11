import { ApiError } from '../api/client.ts'
import type { ApiClient } from '../api/client.ts'
import type { Account } from '../api/types.ts'
import { ru } from './texts.ts'

export type SessionState = { kind: 'checking' } | { kind: 'anonymous' } |
  { kind: 'authenticated'; user: Account } | { kind: 'error' }

export class SessionStore {
  #state: SessionState = { kind: 'checking' }
  #listeners = new Set<() => void>()
  #generation = 0
  #api: Pick<ApiClient['auth'], 'currentSession'>
  constructor(auth: Pick<ApiClient['auth'], 'currentSession'>) { this.#api = auth }
  getSnapshot = () => this.#state
  subscribe = (listener: () => void) => {
    this.#listeners.add(listener)
    return () => { this.#listeners.delete(listener) }
  }
  invalidate = () => { this.#generation++ }
  #publish(state: SessionState) { this.#state = state; for (const listener of this.#listeners) listener() }
  signedIn(user: Account) { this.invalidate(); this.#publish({ kind: 'authenticated', user }) }
  signedOut() { this.invalidate(); this.#publish({ kind: 'anonymous' }) }
  async restore() {
    const generation = ++this.#generation
    this.#publish({ kind: 'checking' })
    try {
      const user = await this.#api.currentSession()
      if (generation === this.#generation) this.#publish({ kind: 'authenticated', user })
    } catch (error) {
      if (generation !== this.#generation) return
      this.#publish(error instanceof ApiError && error.code === 'authentication_required'
        ? { kind: 'anonymous' } : { kind: 'error' })
    }
  }
}

export function authError(error: unknown, mode: 'login' | 'register' | 'logout') {
  if (!(error instanceof ApiError)) return ru.serverError
  if (error.code === 'invalid_credentials') return ru.invalidCredentials
  if (error.code === 'validation_error') return mode === 'register' ? ru.validationError : ru.serverError
  if (error.code === 'csrf_failed') return ru.csrfError
  if (error.code === 'network_error') return ru.networkError
  return ru.serverError
}
