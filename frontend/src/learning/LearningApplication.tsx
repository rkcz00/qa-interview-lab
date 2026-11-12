import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { api } from '../api/index.ts'
import { NavigationLink } from '../auth/NavigationLink.tsx'
import type { Navigate } from '../auth/NavigationLink.tsx'
import type { Destination } from '../auth/routing.ts'
import { SessionStore } from '../auth/session.ts'
import { ru } from '../auth/texts.ts'
import { LearningStore } from './model.ts'
import { learningDestination } from './routing.ts'
import type { LearningLocation } from './routing.ts'
import { learningRu as text } from './texts.ts'
import { assessmentDestination } from '../assessment/routing.ts'
import { assessmentRu } from '../assessment/texts.ts'

interface Props {
  location: LearningLocation
  navigate: Navigate
  requireLogin: (destination: Destination) => void
}

export default function LearningApplication({ location, navigate, requireLogin }: Props) {
  const [session] = useState(() => new SessionStore(api.auth))
  const authentication = useSyncExternalStore(session.subscribe, session.getSnapshot)
  const [store] = useState(() => new LearningStore(api, location))
  const state = useSyncExternalStore(store.subscribe, store.getSnapshot)
  const heading = useRef<HTMLHeadingElement>(null)
  const errorBox = useRef<HTMLDivElement>(null)
  const { content, read } = state
  const destination = learningDestination(location)

  useEffect(() => {
    void session.restore()
    return () => { session.invalidate(); store.invalidate() }
  }, [session, store])
  useEffect(() => {
    if (authentication.kind === 'anonymous') requireLogin(destination)
    if (authentication.kind === 'authenticated') void store.load()
  }, [authentication.kind, destination, requireLogin, store])
  useEffect(() => {
    if (content.kind === 'authentication') requireLogin(destination)
  }, [content.kind, destination, requireLogin])
  useEffect(() => {
    if (authentication.kind === 'authenticated' && content.kind !== 'loading') {
      heading.current?.focus()
      document.title = `${content.kind === 'topic' ? content.article.title : location.topicId === null ? text.catalog : text.topic} — ${ru.brand}`
    }
  }, [authentication.kind, content, location.topicId])
  useEffect(() => { if (read.kind === 'error') errorBox.current?.focus() }, [read])

  const authorized = authentication.kind === 'authenticated' && content.kind !== 'authentication'
  return <main className="learning-shell">
    <nav className="learning-nav" aria-label="Навигация обучения">
      <NavigationLink to="/" navigate={navigate}>{ru.home}</NavigationLink>
      {location.topicId !== null && <NavigationLink to={learningDestination({ topicId: null, language: location.language })} navigate={navigate}>{text.back}</NavigationLink>}
      <NavigationLink to="/progress" navigate={navigate}>{ru.progress}</NavigationLink>
      <NavigationLink to="/session" navigate={navigate}>{text.session}</NavigationLink>
    </nav>
    {!authorized && authentication.kind !== 'error' && <p role="status">{ru.checking}</p>}
    {authentication.kind === 'error' && <section className="learning-card">
      <h1>{text.catalog}</h1><p role="alert">{ru.sessionError}</p>
      <button onClick={() => { void session.restore() }}>{ru.retry}</button>
    </section>}
    {authorized && <>
      <header className="learning-header">
        <p className="eyebrow">QA Interview Lab · {content.kind === 'topic' ? text.article : text.catalog}</p>
        <h1 ref={heading} tabIndex={-1} lang={content.kind === 'topic' ? location.language : undefined}>{content.kind === 'topic' ? content.article.title : content.kind === 'not_found' ? text.notFound : location.topicId === null ? text.catalog : text.topic}</h1>
        {content.kind === 'catalog' && <p>{text.intro}</p>}
        {content.kind !== 'not_found' && <fieldset className="material-language">
          <legend>{text.language}</legend>
          {(['ru', 'en'] as const).map(language => <label key={language}>
            <input type="radio" name="material-language" value={language} checked={location.language === language}
              onChange={() => navigate(learningDestination({ ...location, language }))} />
            <span lang={language}>{language === 'ru' ? 'Русский' : 'English'}</span>
          </label>)}
        </fieldset>}
        {content.kind === 'topic' && <p className="help-text">{text.languageHelp}</p>}
      </header>
      {content.kind === 'loading' && <p role="status">{text.loading}</p>}
      {content.kind === 'error' && <div className="learning-card"><p role="alert">{content.message}</p>
        <button onClick={() => { void store.load() }}>{text.retry}</button></div>}
      {content.kind === 'not_found' && <p role="alert">{text.notFoundHelp}</p>}
      {content.kind === 'catalog' && (content.topics.length === 0 ? <section className="learning-card">
        <h2>{text.empty}</h2><p>{text.emptyHelp}</p>
      </section> : <ul className="topic-list">{content.topics.map(topic => <li key={topic.topic_id}>
        <NavigationLink to={learningDestination({ topicId: topic.topic_id, language: location.language })} navigate={navigate}>{topic.title}</NavigationLink>
      </li>)}</ul>)}
      {content.kind === 'topic' && <>
        <article className="learning-card" aria-labelledby="article-heading">
          <h2 id="article-heading">{text.article}</h2>
          <div className="article-body" lang={location.language}>{content.article.article_body}</div>
        </article>
        <p className="assessment-entry"><NavigationLink to={assessmentDestination({ kind: 'start', id: content.article.topic_id, language: 'ru' })} navigate={navigate}>{assessmentRu.entry}</NavigationLink></p>
        <section className="reading-card" aria-labelledby="reading-heading">
          <h2 id="reading-heading">{text.readHeading}</h2>
          <p className="help-text">{text.readHelp}</p>
          {read.kind === 'loading' && <p role="status">{text.readLoading}</p>}
          {read.kind === 'error' && <>
            <div role="alert" className="form-alert" tabIndex={-1} ref={errorBox}>{read.message}</div>
            <button onClick={() => { void store.refreshRead() }}>{text.readRetry}</button>
          </>}
          {read.kind === 'ready' && <>
            <p role="status">{read.pending ? text.marking : read.at ? text.read : text.unread}</p>
            <button disabled={read.pending || read.at !== null} onClick={() => { void store.markRead() }}>
              {read.pending ? text.marking : read.at ? text.marked : text.markRead}
            </button>
          </>}
        </section>
        <section className="learning-card glossary" aria-labelledby="terms-heading">
          <h2 id="terms-heading">{text.terms}</h2>
          <dl lang={location.language}>{content.terms.map(term => <div key={term.term_id}>
            <dt>{term.name}</dt><dd>{term.definition}</dd>
          </div>)}</dl>
        </section>
      </>}
    </>}
  </main>
}
