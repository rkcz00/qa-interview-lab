export type Language = 'ru' | 'en'

export interface Account {
  user_id: string
  email: string
}

export interface TopicSummary {
  topic_id: string
  title: string
}

export interface Article extends TopicSummary {
  language: Language
  article_body: string
}

export interface Term {
  term_id: string
  position: number
  language: Language
  name: string
  definition: string
}

export interface PublicChoice {
  choice_id: string
  position: number
  text: string
}

export interface PublicQuestion {
  question_id: string
  position: number
  question_type: 'single_choice' | 'multiple_choice'
  text: string
  choices: PublicChoice[]
}

export interface PendingAttempt {
  attempt_id: string
  topic_id: string
  status: 'in_progress'
  language: Language
  questions: PublicQuestion[]
}

export interface Result {
  correct_count: number
  total_count: number
  percentage: number
}

export interface SubmittedAttempt {
  attempt_id: string
  topic_id: string
  topic_title: string
  status: 'submitted'
  submitted_language: Language
  submitted_at: string
  result: Result
}

export type Attempt = PendingAttempt | SubmittedAttempt

export interface Answer {
  question_id: string
  choice_ids: readonly string[]
}

export interface Progress {
  topic_id: string
  article_read_at: string | null
  best_result: Result | null
  mastered: boolean
}

export interface DataEnvelope<T> {
  data: T
}

// Messages are normalized to arrays; no raw response or request is retained.
export type ErrorFields = Readonly<Record<string, readonly string[]>>

export interface ErrorEnvelope {
  error: {
    code: string
    message: string
    fields?: ErrorFields
  }
}
