import type {
  Account, Article, PendingAttempt, Progress, PublicChoice, PublicQuestion, Result, SubmittedAttempt, Term, TopicSummary,
} from '../src/api/types.ts'
import type { ApiClient } from '../src/api/client.ts'

type Assert<T extends true> = T
type Forbidden = 'password' | 'password_hash' | 'session_id' | 'csrf_token' | 'is_correct' | 'correct_answer' |
  'server_key' | 'snapshot' | 'content_snapshot' | 'submitted_answers' | 'revision'
type Public = Account | Article | TopicSummary | Term | PublicChoice | PublicQuestion | PendingAttempt | SubmittedAttempt | Result | Progress
type AllKeys<T> = T extends unknown ? keyof T : never

export type NoSensitiveResponseFields = Assert<Extract<AllKeys<Public>, Forbidden> extends never ? true : false>
export type ExactLanguages = Assert<Parameters<ApiClient['assessment']['start']>[1] extends 'ru' | 'en' ? true : false>
export type BootstrapHidesToken = Assert<Awaited<ReturnType<ApiClient['auth']['bootstrap']>> extends void ? true : false>
export type ExactResultKeys = Assert<keyof Result extends 'correct_count' | 'total_count' | 'percentage' ? true : false>
