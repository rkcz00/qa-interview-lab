import type { ProgressView } from './model.ts'
import { progressRu as text } from './texts.ts'
import { formatPercentage } from '../assessment/answers.ts'

export function OverallProgress({ view }: { view: ProgressView }) {
  return <section className="overall-progress" aria-label={text.overall}>
    <p className="help-text">{text.overall}</p>
    <p className="overall-percentage">{formatPercentage(view.percentage)}</p>
    <progress max={100} value={view.percentage} aria-label={text.overall} />
    <p className="overall-counter">{text.counter(view.mastered, view.total)}</p>
  </section>
}
