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

export interface TopicSection {
  section_id: string
  position: number
  title: string
  article_body: string
}

export interface SectionsArticle extends TopicSummary {
  language: Language
  sections: TopicSection[]
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

export type PracticeNormalization = 'lf_trim_outer_v1' | 'lf_exact_v1'
export type PracticeBlock = 'article_not_read' | 'test_not_submitted'
export interface PracticePreview {
  topic_id: string
  task_id: string
  practice_kind: 'single_correct_answer'
  language: Language
  title: string
  can_start: boolean
  blocked_by: PracticeBlock[]
  normalization_mode: PracticeNormalization
  answer_max_length: 5000
}
export interface PublicPracticeTask {
  practice_kind: 'single_correct_answer'
  source_type: 'python' | 'sql' | 'other'
  title: string
  prompt: string
  source_text: string
  input_data: string
  environment: string
  output_spec: string
  normalization_mode: PracticeNormalization
  answer_max_length: 5000
}
export interface PendingPractice {
  submission_id: string
  topic_id: string
  task_id: string
  status: 'in_progress'
  language: Language
  task: PublicPracticeTask
}
export interface SubmittedPractice {
  submission_id: string
  topic_id: string
  task_id: string
  task_title: string
  status: 'submitted'
  submitted_language: Language
  submitted_at: string
  result: { verdict: 'correct' | 'incorrect' }
}
export type PracticeSubmission = PendingPractice | SubmittedPractice

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

export type ActivityStatus = 'unattempted' | 'failed' | 'passed'

export interface TopicCompletion {
  topic_id: string
  article_read_at: string | null
  test: { status: ActivityStatus; best_result: Result | null }
  practice: { task_id: string; status: ActivityStatus } | null
  completion_progress: number
  mastered: boolean
}

export interface CompletionProgress {
  progress_generation: string
  overall_completion_progress: number
  topics: TopicCompletion[]
}

export interface ResetProgress {
  progress_generation: string
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
