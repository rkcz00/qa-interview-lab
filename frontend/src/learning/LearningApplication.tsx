import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { api } from '../api/index.ts'
import { NavigationLink } from '../auth/NavigationLink.tsx'
import type { Navigate } from '../auth/NavigationLink.tsx'
import type { Destination } from '../auth/routing.ts'
import { SessionStore } from '../auth/session.ts'
import { ru } from '../auth/texts.ts'
import { LearningStore } from './model.ts'
import { learningDestination, sectionFromHash } from './routing.ts'
import type { LearningLocation } from './routing.ts'
import { learningRu as text } from './texts.ts'
import { useSectionReads } from './ReadingContext.ts'
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
import { PracticeEntry } from '../practice/PracticeEntry.tsx'

interface Props {
  location: LearningLocation
  hash: string
  navigate: Navigate
  requireLogin: (destination: Destination) => void
}

export default function LearningApplication({ location, hash, navigate, requireLogin }: Props) {
  const reads = useSectionReads()
  const [session] = useState(() => new SessionStore(api.auth))
  const [sessionPage, setSessionPage] = useState<string | null>(null)
  const [controlsPage, setControlsPage] = useState<string | null>(null)
  const authentication = useSyncExternalStore(session.subscribe, session.getSnapshot)
  const [store] = useState(() => new LearningStore(api, location, reads))
  const { content, read } = useSyncExternalStore(store.subscribe, store.getSnapshot)
  const sectionId = location.sectionId ?? null
  const pageKey = (location.topicId ?? 'catalog') + '/' + (sectionId ?? 'contents')
  const destination = learningDestination(location)
  const errorBox = useRef<HTMLDivElement>(null)
  const ownerReady = sessionPage === pageKey && authentication.kind === 'authenticated' && reads.owner === authentication.user.user_id
  const matches = content.kind === 'topic' && content.topic.topic_id === location.topicId && content.topic.language === location.language &&
    (content.article?.section.section_id ?? null) === sectionId
  const hasContent = matches || content.kind === 'catalog' && location.topicId === null
  const ready = ownerReady && (hasContent || content.kind === 'not_found' || content.kind === 'error')
  const legacyTarget = sectionFromHash(hash)
  const redirecting = matches && sectionId === null && legacyTarget !== null &&
    content.topic.sections.some(section => section.section_id === legacyTarget)
  const heading = usePageHeadingFocus(ready && !redirecting, pageKey)
  const saveRead = useCallback(() => { void store.markRead() }, [store])
  const marker = useAutomaticRead(ownerReady && matches && sectionId !== null && read.kind === 'ready' &&
    !read.pending && !read.retryRequired && !read.complete && read.sections[sectionId] === null, saveRead)
  const expired = useCallback(() => requireLogin(destination), [requireLogin, destination])
  const sections = matches ? content.topic.sections : []
  const validLegacy = !sectionId && sectionFromHash(hash)
  const invalidAnchor = Boolean(hash && (!sectionId ? !validLegacy || !sections.some(section => section.section_id === validLegacy) :
    hash !== '#section-' + sectionId))

  useEffect(() => {
    let active = true
    setSessionPage(null)
    setControlsPage(null)
    void session.restore().then(() => { if (active) setSessionPage(pageKey) })
    return () => { active = false }
  }, [session, pageKey])
  useEffect(() => () => { session.invalidate(); store.invalidate() }, [session, store])
  useEffect(() => {
    if (sessionPage !== pageKey) return
    if (authentication.kind === 'anonymous') requireLogin(destination)
    if (authentication.kind === 'authenticated') {
      reads.bindOwner(authentication.user.user_id)
      void store.load(location)
    }
    return () => { store.invalidate() }
  }, [authentication, sessionPage, pageKey, destination, reads, requireLogin, store])
  useEffect(() => { if (content.kind === 'authentication') requireLogin(destination) }, [content.kind, destination, requireLogin])
  useEffect(() => {
    if (matches && validLegacy && sections.some(section => section.section_id === validLegacy)) {
      navigate(learningDestination(location, validLegacy), true)
    }
  }, [matches, validLegacy, destination, navigate, sections])
  useEffect(() => {
    if (matches) document.title = `${content.article?.section.title ?? content.topic.title} — ${ru.brand}`
  }, [content, matches])
  useEffect(() => {
    if (ownerReady && hasContent && !redirecting) setControlsPage(pageKey)
  }, [ownerReady, hasContent, redirecting, pageKey])
  useEffect(() => { if (read.kind === 'error') errorBox.current?.focus() }, [read.kind, read.kind === 'error' ? read.message : null, pageKey])

  const authorized = ownerReady && content.kind !== 'authentication'
  const notFound = sectionId ? text.sectionNotFound : text.notFound
  const title = matches ? content.article?.section.title ?? content.topic.title :
    content.kind === 'not_found' ? notFound : location.topicId === null ? text.catalog : sectionId ? text.section : text.topic
  return <AppShell navigate={navigate} canLogout={authentication.kind === 'authenticated'} topicId={location.topicId} materialLanguage={location.language}>
    {location.topicId !== null && <p><NavigationLink to={learningDestination({ topicId: null, language: location.language })} navigate={navigate}>{text.back}</NavigationLink></p>}
    {!authorized && authentication.kind !== 'error' && <LoadingState message={ru.checking} />}
    {authentication.kind === 'error' && <><h1>{text.topic}</h1><Notice>{ru.sessionError}</Notice>
      <Button variant="secondary" onClick={() => { void session.restore() }}>{ru.retry}</Button></>}
    {authorized && <>
      <header className="learning-header">
        <p className="eyebrow">QA Interview Lab · {location.topicId === null ? text.catalog : sectionId ? text.section : text.contents}</p>
        {matches && sectionId && <p className="topic-context"><NavigationLink to={learningDestination(location, null)} navigate={navigate}>
          <span lang={location.language}>{content.topic.title}</span> — {text.contentsAndTerms}</NavigationLink></p>}
        <h1 ref={heading} id={sectionId ? 'section-' + sectionId : undefined} tabIndex={-1} lang={matches ? location.language : undefined}>{title}</h1>
        {content.kind === 'catalog' && <p>{text.intro}</p>}
        {content.kind !== 'not_found' && <LanguageSelector name="material-language" legend={text.language} language={location.language} disabled={controlsPage !== pageKey}
          choose={language => navigate(learningDestination({ ...location, language }))} />}
        {matches && <p className="help-text">{text.languageHelp}</p>}
      </header>
      {!ready && <LoadingState message={text.loading} />}
      {content.kind === 'error' && <div className="learning-card"><Notice>{content.message}</Notice>
        <Button variant="secondary" onClick={() => { void store.load(location) }}>{text.retry}</Button></div>}
      {content.kind === 'not_found' && <Notice>{text.notFoundHelp}</Notice>}
      {content.kind === 'catalog' && location.topicId === null && (content.topics.length === 0 ?
        <EmptyState title={text.empty} description={text.emptyHelp} heading /> : <ul className="topic-list">{content.topics.map(topic => <li key={topic.topic_id}>
          <NavigationLink to={learningDestination({ topicId: topic.topic_id, language: location.language })} navigate={navigate}>{topic.title}</NavigationLink>
        </li>)}</ul>)}
      {matches && <>
        {invalidAnchor && <Notice>{text.invalidAnchor}</Notice>}
        <nav className="learning-card section-navigation" aria-label={text.contents}>
          <h2>{text.contents}</h2>
          <ol>{sections.map(section => <li key={section.section_id}>
            <NavigationLink to={learningDestination(location, section.section_id)} navigate={navigate} current={section.section_id === sectionId ? 'page' : undefined}>
              <span lang={location.language}>{section.title}</span>
            </NavigationLink>
            <span className="section-read-state">{reads.phase(content.topic.topic_id, section.section_id) === 'read' ? text.marked :
              reads.phase(content.topic.topic_id, section.section_id) === 'pending' ? text.marking : text.sectionUnread}</span>
          </li>)}</ol>
          {content.article && <div className="section-controls">
            {content.article.previous_section_id && <NavigationLink to={learningDestination(location, content.article.previous_section_id)} navigate={navigate}>{text.previousSection}</NavigationLink>}
            {content.article.next_section_id && <NavigationLink to={learningDestination(location, content.article.next_section_id)} navigate={navigate}>{text.nextSection}</NavigationLink>}
          </div>}
        </nav>
        {content.article && <article className="learning-card reader-section" aria-labelledby={'section-' + sectionId} lang={location.language}>
          <div className="article-body" lang={location.language}>{content.article.section.article_body}</div>
          <span ref={marker} className="article-end" data-section-id={sectionId ?? undefined} aria-hidden="true" />
        </article>}
        <section className="reading-card" aria-labelledby="reading-heading">
          <h2 id="reading-heading">{text.readHeading}</h2><p className="help-text">{text.readHelp}</p>
          {read.kind === 'loading' && <LoadingState message={text.readLoading} />}
          {read.kind === 'error' && <><Notice tabIndex={-1} ref={errorBox}>{read.message}</Notice>
            <Button variant="secondary" onClick={() => { void store.refreshRead() }}>{text.readRetry}</Button></>}
          {read.kind === 'ready' && <>
            <p className="reading-counter">{text.readSections}: {read.reading.read_sections} / {read.reading.total_sections}</p>
            {read.pending ? <LoadingState message={text.marking} /> :
              <Notice tone={read.complete ? 'success' : 'info'}>{read.complete ? text.read : text.unread}</Notice>}
            {read.retryRequired && <><p>{text.checkedUnread}</p><Button variant="secondary" onClick={() => store.allowRetry()}>{text.retrySave}</Button></>}
          </>}
        </section>
        {read.kind === 'ready' && !read.complete && <Notice tone="info">{text.sectionReadRequired}</Notice>}
        <p className="assessment-entry"><NavigationLink to={assessmentDestination({ kind: 'start', id: content.topic.topic_id, language: 'ru' })} navigate={navigate} className="ui-button ui-button--primary">{assessmentRu.entry}</NavigationLink></p>
        <PracticeEntry key={content.topic.topic_id} topicId={content.topic.topic_id} language={location.language} navigate={navigate} expired={expired}
          refreshKey={read.kind === 'ready' ? String(read.complete) : read.kind} />
        <section className="learning-card glossary" aria-labelledby="terms-heading">
          <h2 id="terms-heading">{text.terms}</h2>
          <dl lang={location.language}>{content.terms.map(term => <div key={term.term_id}><dt>{term.name}</dt><dd>{term.definition}</dd></div>)}</dl>
        </section>
      </>}
    </>}
  </AppShell>
}
