import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { api } from '../api/index.ts'
import { NavigationLink } from '../auth/NavigationLink.tsx'
import type { Navigate } from '../auth/NavigationLink.tsx'
import type { Destination } from '../auth/routing.ts'
import { SessionStore } from '../auth/session.ts'
import { ru } from '../auth/texts.ts'
import { assessmentDestination } from '../assessment/routing.ts'
import { formatPercentage } from '../assessment/answers.ts'
import { learningDestination } from '../learning/routing.ts'
import { attemptDate, ProgressStore } from './model.ts'
import { progressRu as text } from './texts.ts'

export default function ProgressApplication({ navigate, requireLogin }: { navigate: Navigate; requireLogin: (destination: Destination) => void }) {
  const [session] = useState(() => new SessionStore(api.auth))
  const authentication = useSyncExternalStore(session.subscribe, session.getSnapshot)
  const [store] = useState(() => new ProgressStore(api))
  const state = useSyncExternalStore(store.subscribe, store.getSnapshot)
  const heading = useRef<HTMLHeadingElement>(null)
  const errorBox = useRef<HTMLDivElement>(null)
  useEffect(() => { void session.restore(); return () => { session.invalidate(); store.invalidate() } }, [session, store])
  useEffect(() => {
    if (authentication.kind === 'anonymous') requireLogin('/progress')
    if (authentication.kind === 'authenticated') void store.load()
  }, [authentication.kind, requireLogin, store])
  useEffect(() => { if (state.kind === 'authentication') requireLogin('/progress') }, [state.kind, requireLogin])
  useEffect(() => { if (state.kind === 'ready') heading.current?.focus(); if (state.kind === 'error') errorBox.current?.focus() }, [state.kind])
  const ready = authentication.kind === 'authenticated' && state.kind === 'ready' ? state.view : null
  return <main className="learning-shell progress-shell">
    <nav className="learning-nav" aria-label="Навигация прогресса">
      <NavigationLink to="/" navigate={navigate}>{ru.home}</NavigationLink>
      <NavigationLink to="/topics" navigate={navigate}>{ru.topics}</NavigationLink>
      <NavigationLink to="/session" navigate={navigate}>Мой аккаунт</NavigationLink>
    </nav>
    <h1 tabIndex={-1} ref={heading}>{text.title}</h1>
    <p>{text.intro}</p>
    {authentication.kind === 'error' && <><p role="alert">{ru.sessionError}</p>
      <button onClick={() => { void session.restore() }}>{ru.retry}</button></>}
    {(authentication.kind === 'checking' || authentication.kind === 'anonymous' ||
      (authentication.kind === 'authenticated' && (state.kind === 'loading' || state.kind === 'authentication'))) && <p role="status">{text.loading}</p>}
    {authentication.kind === 'authenticated' && state.kind === 'error' && <>
      <div className="form-alert" role="alert" tabIndex={-1} ref={errorBox}>{state.message}</div>
      <button onClick={() => { void store.load() }}>{text.retry}</button>
    </>}
    {ready && <>
      <button className="progress-refresh" onClick={() => { void store.load() }}>{text.refresh}</button>
      {!ready.hasSavedProgress && <p className="help-text">{text.noProgress}</p>}
      <section aria-labelledby="progress-topics-heading">
        <h2 id="progress-topics-heading">{text.topics}</h2>
        {ready.topics.length === 0 ? <p>{text.noTopics}</p> : <ul className="topic-progress-list">
          {ready.topics.map(topic => <li className="progress-card" key={topic.topicId} data-topic-id={topic.topicId}>
            <h3 lang={topic.titleLanguage}>{topic.available ?
              <NavigationLink to={learningDestination({ topicId: topic.topicId, language: 'ru' })} navigate={navigate}>{topic.title}</NavigationLink> : topic.title}</h3>
            <p className="help-text">{topic.available ? text.available : text.unavailable}
              {topic.titleSource === 'history' && <> · {text.historicalTitle}</>}
              {topic.titleSource === 'unavailable' && <> · {text.missingTitle}</>}</p>
            <dl className="progress-stats">
              <div><dt>{text.article}</dt><dd>{topic.progress ? topic.progress.readAt ? text.read : text.unread : text.unknown}</dd></div>
              <div><dt>{text.mastery}</dt><dd>{topic.progress ? topic.progress.mastered ? text.mastered : text.unmastered : text.unknown}</dd></div>
              <div><dt>{text.best}</dt><dd>{!topic.progress ? text.unknown : topic.progress.bestResult ?
                `${topic.progress.bestResult.correct_count} из ${topic.progress.bestResult.total_count} (${formatPercentage(topic.progress.bestResult.percentage)})` : text.noResult}</dd></div>
            </dl>
            {!topic.progress && <p className="help-text">{text.changedDuringLoad}</p>}
          </li>)}
        </ul>}
      </section>
      <section aria-labelledby="progress-history-heading" className="progress-history">
        <h2 id="progress-history-heading">{text.history}</h2>
        <p className="help-text">{text.timezone}</p>
        {ready.history.length === 0 ? <p>{text.noHistory}</p> : <ol className="attempt-history-list">
          {ready.history.map(attempt => {
            const date = attemptDate(attempt.submittedAt)
            return <li className="progress-card" key={attempt.attemptId} data-attempt-id={attempt.attemptId}>
              <h3 lang={attempt.language}>{attempt.title}</h3>
              <dl className="progress-stats">
                <div><dt>{text.date}</dt><dd>{date.iso ? <time dateTime={date.iso}>{date.text}</time> : date.text}</dd></div>
                <div><dt>{text.language}</dt><dd>{attempt.language === 'ru' ? 'Русский' : <span lang="en">English</span>}</dd></div>
                <div><dt>{text.correctCount}</dt><dd>{attempt.result.correct_count}</dd></div>
                <div><dt>{text.totalCount}</dt><dd>{attempt.result.total_count}</dd></div>
                <div><dt>{text.percentage}</dt><dd>{formatPercentage(attempt.result.percentage)}</dd></div>
              </dl>
              <NavigationLink to={assessmentDestination({ kind: 'attempt', id: attempt.attemptId, language: attempt.language })} navigate={navigate}>{text.openResult}</NavigationLink>
            </li>
          })}
        </ol>}
      </section>
    </>}
  </main>
}
