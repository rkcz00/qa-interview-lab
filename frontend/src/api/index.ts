import { createApiClient } from './client.ts'

export { ApiError, createApiClient } from './client.ts'
export type { ApiClient, ApiClientOptions } from './client.ts'
export type * from './types.ts'

export const api = createApiClient({
  baseUrl: import.meta.env.VITE_API_BASE_URL ?? '/api/v1/',
  origin: window.location.origin,
})
