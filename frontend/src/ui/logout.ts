import { ApiError } from '../api/client.ts'
import type { ApiClient } from '../api/client.ts'
import { authError } from '../auth/session.ts'

type State = { kind: 'ready' | 'pending' | 'signed_out' } | { kind: 'error'; message: string }

export class LogoutStore {
  #state: State = { kind: 'ready' }
  #listeners = new Set<() => void>()
  #generation = 0
  #auth: Pick<ApiClient['auth'], 'logout' | 'currentSession'>
  constructor(auth: Pick<ApiClient['auth'], 'logout' | 'currentSession'>) { this.#auth = auth }
  getSnapshot = () => this.#state
  subscribe = (listener: () => void) => { this.#listeners.add(listener); return () => { this.#listeners.delete(listener) } }
  invalidate = () => { this.#generation++ }
  #publish(state: State) { this.#state = state; for (const listener of this.#listeners) listener() }

  async logout() {
    if (this.#state.kind === 'pending' || this.#state.kind === 'signed_out') return
    const generation = ++this.#generation
    this.#publish({ kind: 'pending' })
    let signedOut = false
    let message = ''
    try {
      await this.#auth.logout()
      signedOut = true
    } catch (error) {
      signedOut = error instanceof ApiError && error.code === 'authentication_required'
      message = authError(error, 'logout')
      if (error instanceof ApiError && error.code === 'network_error') {
        try { await this.#auth.currentSession() }
        catch (check) { signedOut = check instanceof ApiError && check.code === 'authentication_required' }
      }
    }
    if (generation === this.#generation) this.#publish(signedOut ? { kind: 'signed_out' } : { kind: 'error', message })
  }
}
