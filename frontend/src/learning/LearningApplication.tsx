import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
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
import { AppShell } from '../ui/AppShell.tsx'
import { LanguageSelector } from '../ui/LanguageSelector.tsx'
import { usePageHeadingFocus } from '../ui/usePageHeadingFocus.ts'
import { Button } from '../ui/Button.tsx'
import { Notice } from '../ui/Notice.tsx'
import { LoadingState } from '../ui/LoadingState.tsx'
import { EmptyState } from '../ui/EmptyState.tsx'
import { useAutomaticRead } from './useAutomaticRead.ts'
import { notifyProgressChanged } from '../ui/OverviewContext.tsx'

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
  const errorBox = useRef<HTMLDivElement>(null)
  const { content, read } = state
  const heading = usePageHeadingFocus(authentication.kind === 'authenticated' && !['loading', 'authentication'].includes(content.kind))
  const destination = learningDestination(location)
  const saveRead = useCallback(() => { void store.markRead() }, [store])
  const articleEnd = useAutomaticRead(content.kind === 'topic' && read.kind === 'ready' && !read.pending && read.at === null, saveRead)

  useEffect(() => {
    void session.restore()
    return () => { session.invalidate(); store.invalidate() }
  }, [session, store])
  useEffect(() => {
    if (authentication.kind === 'anonymous') requireLogin(destination)
    if (authentication.kind === 'authenticated') void store.load(location)
  }, [authentication.kind, destination, requireLogin, store])
  useEffect(() => {
    if (content.kind === 'authentication') requireLogin(destination)
  }, [content.kind, destination, requireLogin])
  useEffect(() => {
    if (authentication.kind === 'authenticated' && content.kind !== 'loading') {
      document.title = `${content.kind === 'topic' ? content.article.title : location.topicId === null ? text.catalog : text.topic} — ${ru.brand}`
    }
  }, [authentication.kind, content, location.topicId])
  useEffect(() => { if (read.kind === 'ready' && read.at !== null) notifyProgressChanged() }, [read])

  const authorized = authentication.kind === 'authenticated' && content.kind !== 'authentication'
  return <AppShell navigate={navigate} canLogout={authentication.kind === 'authenticated'} topicId={location.topicId}>
    {location.topicId !== null && <p><NavigationLink to={learningDestination({ topicId: null, language: location.language })} navigate={navigate}>{text.back}</NavigationLink></p>}
    {!authorized && authentication.kind !== 'error' && <LoadingState message={ru.checking} />}
    {authentication.kind === 'error' && <section className="learning-card">
      <h1>{text.catalog}</h1><Notice>{ru.sessionError}</Notice>
      <Button variant="secondary" onClick={() => { void session.restore() }}>{ru.retry}</Button>
    </section>}
    {authorized && <>
      <header className="learning-header">
        <p className="eyebrow">QA Interview Lab · {content.kind === 'topic' ? text.article : text.catalog}</p>
        <h1 ref={heading} tabIndex={-1} lang={content.kind === 'topic' ? location.language : undefined}>{content.kind === 'topic' ? content.article.title : content.kind === 'not_found' ? text.notFound : location.topicId === null ? text.catalog : text.topic}</h1>
        {content.kind === 'catalog' && <p>{text.intro}</p>}
        {content.kind !== 'not_found' && <LanguageSelector name="material-language" legend={text.language} language={location.language}
          choose={language => navigate(learningDestination({ ...location, language }))} />}
        {content.kind === 'topic' && <p className="help-text">{text.languageHelp}</p>}
      </header>
      {content.kind === 'loading' && <LoadingState message={text.loading} />}
      {content.kind === 'error' && <div className="learning-card"><Notice>{content.message}</Notice>
        <Button variant="secondary" onClick={() => { void store.load() }}>{text.retry}</Button></div>}
      {content.kind === 'not_found' && <Notice>{text.notFoundHelp}</Notice>}
      {content.kind === 'catalog' && (content.topics.length === 0 ? <EmptyState title={text.empty} description={text.emptyHelp} heading /> : <ul className="topic-list">{content.topics.map(topic => <li key={topic.topic_id}>
        <NavigationLink to={learningDestination({ topicId: topic.topic_id, language: location.language })} navigate={navigate}>{topic.title}</NavigationLink>
      </li>)}</ul>)}
      {content.kind === 'topic' && <>
        <article className="learning-card" aria-labelledby="article-heading">
          <h2 id="article-heading">{text.article}</h2>
          <div className="article-body" lang={location.language}>{content.article.article_body}</div>
          <span ref={articleEnd} className="article-end" aria-hidden="true" />
        </article>
        <p className="assessment-entry"><NavigationLink to={assessmentDestination({ kind: 'start', id: content.article.topic_id, language: 'ru' })} navigate={navigate} className="ui-button ui-button--primary">{assessmentRu.entry}</NavigationLink></p>
        <section className="reading-card" aria-labelledby="reading-heading">
          <h2 id="reading-heading">{text.readHeading}</h2>
          <p className="help-text">{text.readHelp}</p>
          {read.kind === 'loading' && <LoadingState message={text.readLoading} />}
          {read.kind === 'error' && <>
            <Notice tabIndex={-1} ref={errorBox}>{read.message}</Notice>
            <Button variant="secondary" onClick={() => { void store.refreshRead() }}>{text.readRetry}</Button>
          </>}
          {read.kind === 'ready' && <>
            {read.pending ? <LoadingState message={text.marking} /> : <Notice tone={read.at ? 'success' : 'info'}>{read.at ? text.read : text.unread}</Notice>}
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
  </AppShell>
}
