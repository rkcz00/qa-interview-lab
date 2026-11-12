import type { Answer, PendingAttempt, Result } from '../api/types.ts'

export type Selection = ReadonlyMap<string, readonly string[]>

export function selectChoice(attempt: PendingAttempt, selected: Selection, questionId: string, choiceId: string, checked: boolean): Selection {
  const question = attempt.questions.find(item => item.question_id === questionId)
  if (!question || !question.choices.some(choice => choice.choice_id === choiceId)) throw new RangeError('Unknown assessment choice')
  const next = new Map(selected)
  const values = new Set(selected.get(questionId) ?? [])
  if (question.question_type === 'single_choice' && checked) next.set(questionId, [choiceId])
  else {
    if (checked) values.add(choiceId)
    else values.delete(choiceId)
    next.set(questionId, [...values])
  }
  return next
}

export function answerPayload(attempt: PendingAttempt, selected: Selection): readonly Answer[] {
  const known = new Set(attempt.questions.map(question => question.question_id))
  if ([...selected.keys()].some(key => !known.has(key))) throw new RangeError('Unknown assessment question')
  return Object.freeze(attempt.questions.map(question => {
    const ids = selected.get(question.question_id) ?? []
    if (new Set(ids).size !== ids.length || ids.some(id => !question.choices.some(choice => choice.choice_id === id)) ||
        (question.question_type === 'single_choice' && ids.length > 1)) throw new RangeError('Invalid assessment selection')
    return Object.freeze({
      question_id: question.question_id,
      choice_ids: Object.freeze(question.choices.filter(choice => ids.includes(choice.choice_id)).map(choice => choice.choice_id)),
    })
  }))
}

export function publicResult(result: Result): Result {
  return { correct_count: result.correct_count, total_count: result.total_count, percentage: result.percentage }
}

export function formatPercentage(percentage: number): string {
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(percentage) + '%'
}

export function questionStructure(attempt: PendingAttempt): string {
  return JSON.stringify(attempt.questions.map(question => ({
    id: question.question_id, type: question.question_type, position: question.position,
    choices: question.choices.map(choice => [choice.choice_id, choice.position]),
  })))
}
