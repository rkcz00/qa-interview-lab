import { useEffect, useState, useSyncExternalStore } from 'react'
import { api } from '../api/index.ts'
import type { Navigate } from '../auth/NavigationLink.tsx'
import type { Destination } from '../auth/routing.ts'
import { SessionStore } from '../auth/session.ts'
import { ru } from '../auth/texts.ts'
import { progressRu as text } from './texts.ts'
import { OverallProgress } from './OverallProgress.tsx'
import { AppShell } from '../ui/AppShell.tsx'
import { useOverview } from '../ui/OverviewContext.tsx'
import { usePageHeadingFocus } from '../ui/usePageHeadingFocus.ts'
import { Button } from '../ui/Button.tsx'
import { Notice } from '../ui/Notice.tsx'
import { LoadingState } from '../ui/LoadingState.tsx'
import { EmptyState } from '../ui/EmptyState.tsx'
import { NavigationLink } from '../auth/NavigationLink.tsx'
import { formatPercentage } from '../assessment/answers.ts'
import { ResetDialog } from './ResetDialog.tsx'

function ProgressContent({ navigate }: { navigate: Navigate }) {
  const { state, reload, store } = useOverview()
  const heading = usePageHeadingFocus(state.kind === 'ready' || state.kind === 'error')
  return <>
    <h1 tabIndex={-1} ref={heading}>{text.title}</h1>
    <p>{text.intro}</p>
    {state.kind === 'loading' && <LoadingState message={text.loading} />}
    {state.kind === 'error' && <><Notice>{state.message}</Notice><Button variant="secondary" onClick={reload}>{text.retry}</Button></>}
    {state.kind === 'ready' && <>
      <OverallProgress view={state.view} />
      {state.view.total === 0 && <EmptyState title={text.empty} />}
      {state.view.total > 0 && <section aria-labelledby="completion-topics-title">
        <h2 id="completion-topics-title">{text.topics}</h2>
        <ul className="completion-topic-list">
          {state.view.topics.map(topic => <li key={topic.topic_id} className="progress-card completion-topic" data-topic-id={topic.topic_id}>
            <h3><NavigationLink to={`/topics/${encodeURIComponent(topic.topic_id)}`} navigate={navigate}>{topic.title}</NavigationLink></h3>
            <p className="topic-completion-percentage">{text.topicPercentage}: {formatPercentage(topic.completion_progress)}</p>
            <dl className="completion-statuses">
              <div><dt>{text.article}</dt><dd>{topic.article_read_at === null ? text.unread : text.read}</dd></div>
              <div><dt>{text.test}</dt><dd><span className={`activity-status activity-status--${topic.test.status}`}>{text.activity[topic.test.status]}</span>
                {topic.test.best_result !== null && <p className="help-text test-result-counts">
                  {text.best(topic.test.best_result.correct_count, topic.test.best_result.total_count)} ({formatPercentage(topic.test.best_result.percentage)})
                </p>}
              </dd></div>
              <div><dt>{text.practice}</dt><dd>{topic.practice === null ? text.noPractice :
                <span className={`activity-status activity-status--${topic.practice.status}`}>{text.activity[topic.practice.status]}</span>}</dd></div>
              <div><dt>{text.mastery}</dt><dd>{topic.mastered ? text.mastered : text.notMastered}</dd></div>
            </dl>
          </li>)}
        </ul>
      </section>}
      <p>{text.completionRule}</p>
      <p>{text.rule}</p>
      <p className="help-text">{text.scope}</p>
      {state.reset.kind === 'success' && <Notice tone="success">{text.resetSuccess}</Notice>}
      {state.notice && <Notice tone="info">{state.notice}</Notice>}
      {state.reset.kind === 'error' && !state.reset.open && <Notice>{state.reset.message}</Notice>}
      <section className="progress-reset" aria-label={text.reset}>
        <Button variant="secondary" className="reset-trigger" onClick={event => { event.currentTarget.focus(); store.openReset() }}
          disabled={state.reset.kind === 'posting' || state.reset.kind === 'refreshing'}>{text.reset}</Button>
      </section>
      <ResetDialog state={state.reset} store={store} />
    </>}
  </>
}

export default function ProgressApplication({ navigate, requireLogin }: { navigate: Navigate; requireLogin: (destination: Destination) => void }) {
  const [session] = useState(() => new SessionStore(api.auth))
  const authentication = useSyncExternalStore(session.subscribe, session.getSnapshot)
  useEffect(() => { void session.restore(); return () => session.invalidate() }, [session])
  useEffect(() => { if (authentication.kind === 'anonymous') requireLogin('/progress') }, [authentication.kind, requireLogin])
  return <AppShell className="progress-shell" navigate={navigate} canLogout={authentication.kind === 'authenticated'}>
    {authentication.kind === 'error' && <><Notice>{ru.sessionError}</Notice>
      <Button variant="secondary" onClick={() => { void session.restore() }}>{ru.retry}</Button></>}
    {authentication.kind === 'checking' && <LoadingState message={ru.checking} />}
    {authentication.kind === 'authenticated' && <ProgressContent navigate={navigate} />}
  </AppShell>
}
