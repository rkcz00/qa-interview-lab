import { createApiClient } from './client.ts'

export { ApiError, createApiClient } from './client.ts'
export type { ApiClient, ApiClientOptions } from './client.ts'
export type * from './types.ts'

export const api = createApiClient({
  baseUrl: import.meta.env.VITE_API_BASE_URL ?? '/api/v1/',
  origin: window.location.origin,
  onProgressScopeInvalidated: () => window.dispatchEvent(new Event('qil-reading-invalidated')),
  onProgressReset: reason => {
    // A changed session always discards the previous owner's display.
    if (reason === 'session') { window.location.replace('/login'); return }
    // Only an active reset controller may retain its frozen read-only display.
    const unhandled = window.dispatchEvent(new Event('qil-progress-invalidated', { cancelable: true }))
    if (unhandled) window.location.replace('/progress')
  },
})
