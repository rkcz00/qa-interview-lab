import type {
  Account, Article, Attempt, ErrorEnvelope, ErrorFields, Language, PendingAttempt,
  Progress, PublicChoice, PublicQuestion, Result, SubmittedAttempt, Term, TopicSummary,
} from './types.ts'

export type Decoder<T> = (value: unknown) => T

export class ContractError extends Error {
  constructor() {
    super('Unexpected API response.')
  }
}

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new ContractError()
  return value as Record<string, unknown>
}

function object(value: unknown, required: string[], optional: string[] = []) {
  const item = record(value)
  if (required.some(key => !Object.hasOwn(item, key)) ||
      Object.keys(item).some(key => !required.includes(key) && !optional.includes(key))) throw new ContractError()
  return item
}

function text(value: unknown): string {
  if (typeof value !== 'string') throw new ContractError()
  return value
}

function id(value: unknown) {
  const result = text(value)
  if (!result) throw new ContractError()
  return result
}

function integer(value: unknown): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) throw new ContractError()
  return value
}

function language(value: unknown): Language {
  if (value !== 'ru' && value !== 'en') throw new ContractError()
  return value
}

export function arrayOf<T>(decode: Decoder<T>): Decoder<T[]> {
  return value => {
    if (!Array.isArray(value)) throw new ContractError()
    return value.map(decode)
  }
}

export function dataOf<T>(value: unknown, decode: Decoder<T>): T {
  return decode(object(value, ['data']).data)
}

export function csrfToken(value: unknown): string {
  return id(object(value, ['csrf_token']).csrf_token)
}

export function account(value: unknown): Account {
  const item = object(value, ['user_id', 'email'])
  return { user_id: id(item.user_id), email: text(item.email) }
}

export function topicSummary(value: unknown): TopicSummary {
  const item = object(value, ['topic_id', 'title'])
  return { topic_id: id(item.topic_id), title: text(item.title) }
}

export function article(value: unknown): Article {
  const item = object(value, ['topic_id', 'title', 'language', 'article_body'])
  return {
    topic_id: id(item.topic_id), title: text(item.title),
    language: language(item.language), article_body: text(item.article_body),
  }
}

export function term(value: unknown): Term {
  const item = object(value, ['term_id', 'position', 'language', 'name', 'definition'])
  return {
    term_id: id(item.term_id), position: integer(item.position), language: language(item.language),
    name: text(item.name), definition: text(item.definition),
  }
}

function choice(value: unknown): PublicChoice {
  const item = object(value, ['choice_id', 'position', 'text'])
  return { choice_id: id(item.choice_id), position: integer(item.position), text: text(item.text) }
}

function question(value: unknown): PublicQuestion {
  const item = object(value, ['question_id', 'position', 'question_type', 'text', 'choices'])
  if (item.question_type !== 'single_choice' && item.question_type !== 'multiple_choice') throw new ContractError()
  return {
    question_id: id(item.question_id), position: integer(item.position), question_type: item.question_type,
    text: text(item.text), choices: arrayOf(choice)(item.choices),
  }
}

export function pendingAttempt(value: unknown): PendingAttempt {
  const item = object(value, ['attempt_id', 'topic_id', 'status', 'language', 'questions'])
  if (item.status !== 'in_progress') throw new ContractError()
  return {
    attempt_id: id(item.attempt_id), topic_id: id(item.topic_id), status: item.status,
    language: language(item.language), questions: arrayOf(question)(item.questions),
  }
}

function result(value: unknown): Result {
  const item = object(value, ['correct_count', 'total_count', 'percentage'])
  const correct_count = integer(item.correct_count)
  const total_count = integer(item.total_count)
  const percentage = item.percentage
  if (total_count === 0 || correct_count > total_count || typeof percentage !== 'number' ||
      !Number.isFinite(percentage) || percentage < 0 || percentage > 100) throw new ContractError()
  return { correct_count, total_count, percentage }
}

export function submittedAttempt(value: unknown): SubmittedAttempt {
  const item = object(value, [
    'attempt_id', 'topic_id', 'topic_title', 'status', 'submitted_language', 'submitted_at', 'result',
  ])
  if (item.status !== 'submitted') throw new ContractError()
  return {
    attempt_id: id(item.attempt_id), topic_id: id(item.topic_id), topic_title: text(item.topic_title),
    status: item.status, submitted_language: language(item.submitted_language),
    submitted_at: text(item.submitted_at), result: result(item.result),
  }
}

export function attempt(value: unknown): Attempt {
  return record(value).status === 'in_progress' ? pendingAttempt(value) : submittedAttempt(value)
}

export function progress(value: unknown): Progress {
  const item = object(value, ['topic_id', 'article_read_at', 'best_result', 'mastered'])
  if (typeof item.mastered !== 'boolean') throw new ContractError()
  return {
    topic_id: id(item.topic_id),
    article_read_at: item.article_read_at === null ? null : text(item.article_read_at),
    best_result: item.best_result === null ? null : result(item.best_result), mastered: item.mastered,
  }
}

export function errorEnvelope(value: unknown): ErrorEnvelope {
  const item = object(object(value, ['error']).error, ['code', 'message'], ['fields'])
  let fields: ErrorFields | undefined
  if (Object.hasOwn(item, 'fields')) {
    const inputs = ['email', 'password', 'language', 'answers', 'question_id', 'choice_ids', 'topic_id', 'attempt_id', 'non_field_errors']
    fields = Object.fromEntries(Object.entries(record(item.fields)).map(([key, messages]) => {
      if (!inputs.includes(key)) throw new ContractError()
      return [key, typeof messages === 'string' ? [messages] : arrayOf(text)(messages)]
    }))
  }
  return { error: { code: id(item.code), message: text(item.message), ...(fields === undefined ? {} : { fields }) } }
}
