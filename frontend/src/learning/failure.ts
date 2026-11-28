import { ApiError } from '../api/client.ts'

export type LearningFailure = 'authentication' | 'not_found' | 'csrf' | 'network' | 'server'
export function learningFailure(error: unknown): LearningFailure {
  if (!(error instanceof ApiError)) return 'server'
  if (error.status === 403 && error.code === 'authentication_required') return 'authentication'
  if (error.status === 404 && error.code === 'not_found') return 'not_found'
  if (error.status === 403 && error.code === 'csrf_failed') return 'csrf'
  if (error.code === 'network_error') return 'network'
  return 'server'
}
