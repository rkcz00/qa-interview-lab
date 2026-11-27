import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { api } from '../api/index.ts'
import type { TopicSection } from '../api/types.ts'
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
import { PracticeEntry } from '../practice/PracticeEntry.tsx'

interface Props {
  location: LearningLocation
  sectionId: string | null
  navigate: Navigate
  requireLogin: (destination: Destination) => void
}

export default function LearningApplication({ location, sectionId, navigate, requireLogin }: Props) {
  const [session] = useState(() => new SessionStore(api.auth))
  const authentication = useSyncExternalStore(session.subscribe, session.getSnapshot)
  const [store] = useState(() => new LearningStore(api, location))
  const state = useSyncExternalStore(store.subscribe, store.getSnapshot)
  const errorBox = useRef<HTMLDivElement>(null)
  const { content, read } = state
  const focusedSection = useRef<string | null>(null)
  const heading = usePageHeadingFocus(sectionId === null && authentication.kind === 'authenticated' && !['loading', 'authentication'].includes(content.kind))
  const destination = learningDestination(location)
  const saveRead = useCallback((sectionId: string) => { void store.markRead(sectionId) }, [store])
  const expired = useCallback(() => requireLogin(destination), [requireLogin, destination])

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
  useEffect(() => {
    if (read.kind === 'ready' && !read.pending && Object.values(read.sections).some(at => at !== null)) notifyProgressChanged()
  }, [read])
  useEffect(() => {
    if (content.kind !== 'topic') return
    const key = `${content.article.topic_id}/${sectionId ?? ''}`
    if (focusedSection.current === key) return
    focusedSection.current = key
    if (!sectionId || !content.article.sections.some(section => section.section_id === sectionId)) return
    const target = document.getElementById(`section-${sectionId}`)
    target?.focus({ preventScroll: true })
    target?.scrollIntoView({ block: 'start' })
  }, [content, sectionId])

  const authorized = authentication.kind === 'authenticated' && content.kind !== 'authentication'
  const sections = content.kind === 'topic' ? content.article.sections : []
  const currentIndex = Math.max(0, sections.findIndex(section => section.section_id === sectionId))
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
          choose={language => navigate(learningDestination({ ...location, language }, sectionId))} />}
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
          <nav className="section-navigation" aria-label={text.contents}>
            <ol>{sections.map(section => <li key={section.section_id}>
              <NavigationLink to={learningDestination(location, section.section_id)} navigate={navigate}
                current={section.section_id === sections[currentIndex]?.section_id ? 'location' : undefined}>
                <span lang={location.language}>{section.title}</span>
              </NavigationLink>
            </li>)}</ol>
            <p>{text.currentSection}: <span lang={location.language}>{sections[currentIndex]?.title}</span></p>
            <div className="section-controls">
              {currentIndex > 0 && <NavigationLink to={learningDestination(location, sections[currentIndex - 1].section_id)} navigate={navigate}>{text.previousSection}</NavigationLink>}
              {currentIndex < sections.length - 1 && <NavigationLink to={learningDestination(location, sections[currentIndex + 1].section_id)} navigate={navigate}>{text.nextSection}</NavigationLink>}
            </div>
          </nav>
          {sections.map(section => <ReadableSection key={section.section_id} section={section} language={location.language}
            enabled={read.kind === 'ready' && !read.pending && !read.complete && read.sections[section.section_id] === null}
            markRead={saveRead} />)}
        </article>
        <p className="assessment-entry"><NavigationLink to={assessmentDestination({ kind: 'start', id: content.article.topic_id, language: 'ru' })} navigate={navigate} className="ui-button ui-button--primary">{assessmentRu.entry}</NavigationLink></p>
        <PracticeEntry key={content.article.topic_id} topicId={content.article.topic_id} language={location.language} navigate={navigate} expired={expired}
          refreshKey={read.kind === 'ready' ? String(read.complete) : read.kind} />
        <section className="reading-card" aria-labelledby="reading-heading">
          <h2 id="reading-heading">{text.readHeading}</h2>
          <p className="help-text">{text.readHelp}</p>
          {read.kind === 'loading' && <LoadingState message={text.readLoading} />}
          {read.kind === 'error' && <>
            <Notice tabIndex={-1} ref={errorBox}>{read.message}</Notice>
            <Button variant="secondary" onClick={() => { void store.refreshRead() }}>{text.readRetry}</Button>
          </>}
          {read.kind === 'ready' && <>
            {read.pending ? <LoadingState message={text.marking} /> : <Notice tone={read.complete ? 'success' : 'info'}>{read.complete ? text.read : text.unread}</Notice>}
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

function ReadableSection({ section, language, enabled, markRead }: {
  section: TopicSection; language: 'ru' | 'en'; enabled: boolean; markRead: (sectionId: string) => void
}) {
  const save = useCallback(() => markRead(section.section_id), [markRead, section.section_id])
  const marker = useAutomaticRead(enabled, save)
  return <section className="reader-section" aria-labelledby={`section-${section.section_id}`} lang={language}>
    <h2 id={`section-${section.section_id}`} tabIndex={-1}>{section.title}</h2>
    <div className="article-body" lang={language}>{section.article_body}</div>
    <span ref={marker} className="article-end" data-section-id={section.section_id} aria-hidden="true" />
  </section>
}
