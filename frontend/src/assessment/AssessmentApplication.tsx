import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { api } from '../api/index.ts'
import { NavigationLink } from '../auth/NavigationLink.tsx'
import type { Navigate } from '../auth/NavigationLink.tsx'
import type { Destination } from '../auth/routing.ts'
import { SessionStore } from '../auth/session.ts'
import { ru } from '../auth/texts.ts'
import { formatPercentage } from './answers.ts'
import { AttemptStore, StartStore } from './model.ts'
import { assessmentDestination } from './routing.ts'
import type { AssessmentLocation } from './routing.ts'
import { assessmentRu as text } from './texts.ts'
import { AppShell } from '../ui/AppShell.tsx'
import { LanguageSelector } from '../ui/LanguageSelector.tsx'
import { usePageHeadingFocus } from '../ui/usePageHeadingFocus.ts'
import { Button } from '../ui/Button.tsx'
import { Notice } from '../ui/Notice.tsx'
import { LoadingState } from '../ui/LoadingState.tsx'
import { notifyProgressChanged } from '../ui/OverviewContext.tsx'
import { PracticeEntry } from '../practice/PracticeEntry.tsx'
import type { Language } from '../api/types.ts'

interface Props {
  location: AssessmentLocation
  navigate: Navigate
  requireLogin: (destination: Destination) => void
  articleLink: (topicId: string) => Destination
  onTopic?: (topicId: string) => void
  articleLanguage: (topicId: string) => Language
}

function FocusedNotice({ message }: { message: string }) {
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => { box.current?.focus() }, [message])
  return <Notice tabIndex={-1} ref={box}>{message}</Notice>
}

function StartScreen({ location, navigate, articleLink, expired }: Props & { expired: () => void }) {
  const [store] = useState(() => new StartStore(api, location.id))
  const state = useSyncExternalStore(store.subscribe, store.getSnapshot)
  const heading = usePageHeadingFocus(state.kind === 'ready' || state.kind === 'not_found')
  useEffect(() => { void store.load(location.language) }, [store, location.language])
  useEffect(() => () => store.invalidate(), [store])
  useEffect(() => {
    if (state.kind === 'authentication') expired()
    if (state.kind === 'started') navigate(assessmentDestination({ kind: 'attempt', id: state.attemptId, language: state.language }))
  }, [state, expired, navigate])
  const locked = state.kind === 'creating' || state.kind === 'uncertain' || state.kind === 'started'
  return <>
    <p><NavigationLink to={articleLink(location.id)} navigate={navigate}>{text.back}</NavigationLink></p>
    <h1 tabIndex={-1} ref={heading}>{state.kind === 'not_found' ? text.notFound : text.prepare}</h1>
    {state.kind === 'ready' && <h2 lang={state.language}>{state.title}</h2>}
    {state.kind !== 'not_found' && <>
      <LanguageSelector name="test-language" legend={text.language} language={location.language} disabled={locked}
        choose={language => navigate(assessmentDestination({ ...location, language }))} />
      <p className="help-text">{text.languageHelp}</p>
    </>}
    {(state.kind === 'loading' || state.kind === 'authentication') && <LoadingState message={text.loading} />}
    {state.kind === 'not_found' && <Notice>{text.notFoundHelp}</Notice>}
    {state.kind === 'ready' && <>
      <p>{text.startHelp}</p>
      {state.message && <FocusedNotice message={state.message} />}
      <Button onClick={() => { void store.start() }}>{text.begin}</Button>
    </>}
    {state.kind === 'creating' && <><LoadingState message={text.beginning} /><Button busy>{text.beginning}</Button></>}
    {state.kind === 'error' && <><FocusedNotice message={state.message} /><Button variant="secondary" onClick={() => { void store.load(location.language) }}>{text.retryLoad}</Button></>}
    {state.kind === 'uncertain' && <><FocusedNotice message={state.message} /><Button onClick={() => { void store.start(true) }}>{text.newAttempt}</Button></>}
  </>
}

function AttemptScreen({ location, navigate, articleLink, articleLanguage, expired, onTopic }: Props & { expired: () => void }) {
  const [store] = useState(() => new AttemptStore(api.assessment, location.id))
  const state = useSyncExternalStore(store.subscribe, store.getSnapshot)
  const questionHeading = useRef<HTMLHeadingElement>(null)
  const focusPage = state.kind === 'pending' ? 'attempt' : state.kind === 'result' ? 'result' : state.kind === 'not_found' ? 'not_found' : null
  const resultHeading = usePageHeadingFocus(focusPage !== null, focusPage)
  const movedQuestion = useRef(false)
  const answerAdvanced = useRef(false)
  useEffect(() => { void store.load(location.language) }, [store, location.language])
  useEffect(() => () => store.invalidate(), [store])
  useEffect(() => { if (state.kind === 'authentication') expired() }, [state.kind, expired])
  const pending = state.kind === 'pending' ? state : null
  const question = pending?.attempt.questions[pending.index]
  const currentTopic = pending?.attempt.topic_id ?? (state.kind === 'result' ? state.topic.id : null)
  useEffect(() => { if (currentTopic) onTopic?.(currentTopic) }, [currentTopic, onTopic])
  useEffect(() => { if (state.kind === 'result') notifyProgressChanged() }, [state.kind])
  useEffect(() => {
    if (question && movedQuestion.current) { movedQuestion.current = false; questionHeading.current?.focus() }
  }, [question?.question_id])
  useEffect(() => { document.title = `${state.kind === 'result' ? text.result : text.title} — ${ru.brand}` }, [state.kind])
  return <>
    <h1 tabIndex={-1} ref={resultHeading}>{state.kind === 'result' ? text.result : state.kind === 'not_found' ? text.notFound : text.title}</h1>
    {['loading', 'pending'].includes(state.kind) && <>
      <LanguageSelector name="test-language" legend={text.language} language={location.language}
        choose={language => navigate(assessmentDestination({ ...location, language }))} />
      <p className="help-text">{text.languageHelp}</p>
    </>}
    {(state.kind === 'loading' || state.kind === 'authentication') && <LoadingState message={text.loading} />}
    {state.kind === 'error' && <><FocusedNotice message={state.message} /><Button variant="secondary" onClick={() => { void store.load(location.language) }}>{text.retryLoad}</Button></>}
    {state.kind === 'not_found' && <Notice>{text.notFoundHelp}</Notice>}
    {state.kind === 'sending' && <><LoadingState message={text.sending} /><Button busy>{text.sending}</Button></>}
    {state.kind === 'checking' && <><LoadingState message={text.checking} /><Button variant="secondary" busy>{text.checkResult}</Button></>}
    {state.kind === 'uncertain' && <>
      <FocusedNotice message={state.message} />
      {state.canRetry && <p>{text.retryHelp}</p>}
      <div className="assessment-actions">
        <Button variant="secondary" onClick={() => { void store.checkResult() }}>{text.checkResult}</Button>
        {state.canRetry && <Button variant="secondary" onClick={() => { void store.retrySame() }}>{text.retrySame}</Button>}
      </div>
    </>}
    {pending && question && <>
      <p><NavigationLink to={articleLink(pending.attempt.topic_id)} navigate={navigate}>{text.back}</NavigationLink></p>
      <p className="help-text">{text.restored}</p>
      {pending.message && <FocusedNotice message={pending.message} />}
      <fieldset className="question-card" aria-labelledby="question-text">
        <legend>{text.question} {pending.index + 1} {text.of} {pending.attempt.questions.length}</legend>
        <h2 id="question-text" lang={pending.attempt.language} tabIndex={-1} ref={questionHeading}>{question.text}</h2>
        <p>{question.question_type === 'single_choice' ? text.single : text.multiple}</p>
        <div className="answer-options">
          {question.choices.map(choice => <label key={choice.choice_id}>
            <input type={question.question_type === 'single_choice' ? 'radio' : 'checkbox'} name={'answer-' + question.question_id}
              value={choice.choice_id} checked={pending.selected.get(question.question_id)?.includes(choice.choice_id) ?? false}
              onChange={event => store.choose(question.question_id, choice.choice_id, event.currentTarget.checked)} />
            <span lang={pending.attempt.language}>{choice.text}</span>
          </label>)}
        </div>
      </fieldset>
      <p id="answer-confirmation" role="status">{pending.confirmed.has(question.question_id) ? text.answered : text.unconfirmed}</p>
      <p className="help-text">{text.confirmedCount} {pending.confirmed.size} {text.of} {pending.attempt.questions.length}</p>
      <div className="assessment-actions question-navigation">
        <Button variant="secondary" aria-label={text.previousLabel} disabled={pending.index === 0} onClick={() => { movedQuestion.current = true; store.move(pending.index - 1) }}>{text.previous}</Button>
        <Button aria-describedby="answer-confirmation" onMouseDown={event => {
          // The repeated press must not take native focus back from the new heading.
          if (event.detail > 1 && answerAdvanced.current) event.preventDefault()
        }} onClick={event => {
          if (event.detail > 1) {
            if (answerAdvanced.current) questionHeading.current?.focus()
            return
          }
          movedQuestion.current = true
          answerAdvanced.current = store.confirm(question.question_id)
          if (!answerAdvanced.current) movedQuestion.current = false
        }}>{text.answer}</Button>
        <Button variant="secondary" aria-label={text.nextLabel} disabled={pending.index === pending.attempt.questions.length - 1} onClick={() => { movedQuestion.current = true; store.move(pending.index + 1) }}>{text.next}</Button>
      </div>
      <div className="assessment-actions">
        <Button variant="secondary" disabled={!pending.selected.get(question.question_id)?.length} onClick={() => store.clear()}>{text.clear}</Button>
      </div>
      <p className="help-text assessment-submit-help">{text.submitHelp}</p>
      {pending.canFinish && pending.index === pending.attempt.questions.length - 1 && <Button onClick={event => {
        if (event.detail > 1) {
          if (answerAdvanced.current) questionHeading.current?.focus()
          return
        }
        void store.submit()
      }}>{text.submit}</Button>}
    </>}
    {state.kind === 'result' && <section aria-label={text.result}>
      <h2 className="result-topic" lang={state.topic.language}>{state.topic.title}</h2>
      {state.notice && <Notice tone="info">{state.notice}</Notice>}
      <dl className="result-summary">
        <div><dt>{text.correctCount}</dt><dd>{state.result.correct_count}</dd></div>
        <div><dt>{text.totalCount}</dt><dd>{state.result.total_count}</dd></div>
        <div><dt>{text.percentage}</dt><dd>{formatPercentage(state.result.percentage)}</dd></div>
      </dl>
      <div className="assessment-actions">
        <NavigationLink to={articleLink(state.topic.id)} navigate={navigate} className="ui-button ui-button--secondary">{text.back}</NavigationLink>
        <NavigationLink to="/progress" navigate={navigate} className="ui-button ui-button--primary">{text.openProgress}</NavigationLink>
      </div>
      <PracticeEntry topicId={state.topic.id} language={articleLanguage(state.topic.id)} navigate={navigate} expired={expired} />
    </section>}
  </>
}

export default function AssessmentApplication(props: Props) {
  const [topicId, setTopicId] = useState<string | null>(props.location.kind === 'start' ? props.location.id : null)
  const [session] = useState(() => new SessionStore(api.auth))
  const state = useSyncExternalStore(session.subscribe, session.getSnapshot)
  const destination = assessmentDestination(props.location)
  const expired = useCallback(() => props.requireLogin(destination), [props.requireLogin, destination])
  useEffect(() => { void session.restore(); return () => session.invalidate() }, [session])
  useEffect(() => { if (state.kind === 'anonymous') expired() }, [state.kind, expired])
  return <AppShell className="assessment-shell" navigate={props.navigate} canLogout={state.kind === 'authenticated'} topicId={topicId}>
    {(state.kind === 'checking' || state.kind === 'anonymous') && <LoadingState message={ru.checking} />}
    {state.kind === 'error' && <><h1>{text.title}</h1><FocusedNotice message={ru.sessionError} />
      <Button variant="secondary" onClick={() => { void session.restore() }}>{ru.retry}</Button></>}
    {state.kind === 'authenticated' && (props.location.kind === 'start' ? <StartScreen {...props} expired={expired} /> : <AttemptScreen {...props} expired={expired} onTopic={setTopicId} />)}
  </AppShell>
}
