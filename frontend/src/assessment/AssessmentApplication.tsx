import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { api } from '../api/index.ts'
import type { Language } from '../api/types.ts'
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

interface Props {
  location: AssessmentLocation
  navigate: Navigate
  requireLogin: (destination: Destination) => void
  articleLink: (topicId: string) => Destination
}

function Notice({ message }: { message: string }) {
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => { box.current?.focus() }, [message])
  return <div className="form-alert" role="alert" tabIndex={-1} ref={box}>{message}</div>
}

function TestLanguage({ language, disabled, choose }: { language: Language; disabled: boolean; choose: (language: Language) => void }) {
  return <fieldset className="material-language" disabled={disabled}>
    <legend>{text.language}</legend>
    {(['ru', 'en'] as const).map(value => <label key={value}>
      <input type="radio" name="test-language" value={value} checked={language === value} onChange={() => choose(value)} />
      <span lang={value}>{value === 'ru' ? 'Русский' : 'English'}</span>
    </label>)}
  </fieldset>
}

function StartScreen({ location, navigate, articleLink, expired }: Props & { expired: () => void }) {
  const [store] = useState(() => new StartStore(api, location.id))
  const state = useSyncExternalStore(store.subscribe, store.getSnapshot)
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => { void store.load(location.language) }, [store, location.language])
  useEffect(() => () => store.invalidate(), [store])
  useEffect(() => {
    if (state.kind === 'authentication') expired()
    if (state.kind === 'started') navigate(assessmentDestination({ kind: 'attempt', id: state.attemptId, language: state.language }))
  }, [state, expired, navigate])
  useEffect(() => { if (state.kind === 'ready' || state.kind === 'not_found') heading.current?.focus() }, [state.kind])
  const locked = state.kind === 'creating' || state.kind === 'uncertain' || state.kind === 'started'
  return <>
    <p><NavigationLink to={articleLink(location.id)} navigate={navigate}>{text.back}</NavigationLink></p>
    <h1 tabIndex={-1} ref={heading}>{state.kind === 'not_found' ? text.notFound : text.prepare}</h1>
    {state.kind === 'ready' && <h2 lang={state.language}>{state.title}</h2>}
    {state.kind !== 'not_found' && <>
      <TestLanguage language={state.language} disabled={locked} choose={language => navigate(assessmentDestination({ ...location, language }))} />
      <p className="help-text">{text.languageHelp}</p>
    </>}
    {(state.kind === 'loading' || state.kind === 'authentication') && <p role="status">{text.loading}</p>}
    {state.kind === 'not_found' && <p role="alert">{text.notFoundHelp}</p>}
    {state.kind === 'ready' && <>
      <p>{text.startHelp}</p>
      {state.message && <Notice message={state.message} />}
      <button onClick={() => { void store.start() }}>{text.begin}</button>
    </>}
    {state.kind === 'creating' && <><p role="status">{text.beginning}</p><button disabled>{text.beginning}</button></>}
    {state.kind === 'error' && <><Notice message={state.message} /><button onClick={() => { void store.load(location.language) }}>{text.retryLoad}</button></>}
    {state.kind === 'uncertain' && <><Notice message={state.message} /><button onClick={() => { void store.start(true) }}>{text.newAttempt}</button></>}
  </>
}

function AttemptScreen({ location, navigate, articleLink, expired }: Props & { expired: () => void }) {
  const [store] = useState(() => new AttemptStore(api.assessment, location.id))
  const state = useSyncExternalStore(store.subscribe, store.getSnapshot)
  const questionHeading = useRef<HTMLHeadingElement>(null)
  const resultHeading = useRef<HTMLHeadingElement>(null)
  useEffect(() => { void store.load(location.language) }, [store, location.language])
  useEffect(() => () => store.invalidate(), [store])
  useEffect(() => { if (state.kind === 'authentication') expired() }, [state.kind, expired])
  const pending = state.kind === 'pending' ? state : null
  const question = pending?.attempt.questions[pending.index]
  useEffect(() => { questionHeading.current?.focus() }, [question?.question_id, pending?.attempt.language])
  useEffect(() => { document.title = `${state.kind === 'result' ? text.result : text.title} — ${ru.brand}` }, [state.kind])
  useEffect(() => { if (state.kind === 'result') resultHeading.current?.focus() }, [state.kind])
  return <>
    <h1 tabIndex={-1} ref={resultHeading}>{state.kind === 'result' ? text.result : state.kind === 'not_found' ? text.notFound : text.title}</h1>
    {(state.kind === 'loading' || state.kind === 'authentication') && <p role="status">{text.loading}</p>}
    {state.kind === 'error' && <><Notice message={state.message} /><button onClick={() => { void store.load(location.language) }}>{text.retryLoad}</button></>}
    {state.kind === 'not_found' && <p role="alert">{text.notFoundHelp}</p>}
    {state.kind === 'sending' && <><p role="status">{text.sending}</p><button disabled>{text.sending}</button></>}
    {state.kind === 'checking' && <><p role="status">{text.checking}</p><button disabled>{text.checkResult}</button></>}
    {state.kind === 'uncertain' && <>
      <Notice message={state.message} />
      {state.canRetry && <p>{text.retryHelp}</p>}
      <div className="assessment-actions">
        <button onClick={() => { void store.checkResult() }}>{text.checkResult}</button>
        {state.canRetry && <button onClick={() => { void store.retrySame() }}>{text.retrySame}</button>}
      </div>
    </>}
    {pending && question && <>
      <p><NavigationLink to={articleLink(pending.attempt.topic_id)} navigate={navigate}>{text.back}</NavigationLink></p>
      <TestLanguage language={pending.attempt.language} disabled={false} choose={language => navigate(assessmentDestination({ ...location, language }))} />
      <p className="help-text">{text.languageHelp}</p>
      <p className="help-text">{text.restored}</p>
      {pending.message && <Notice message={pending.message} />}
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
      <div className="assessment-actions question-navigation">
        <button disabled={pending.index === 0} onClick={() => store.move(pending.index - 1)}>{text.previous}</button>
        <button disabled={pending.index === pending.attempt.questions.length - 1} onClick={() => store.move(pending.index + 1)}>{text.next}</button>
        <button disabled={!pending.selected.get(question.question_id)?.length} onClick={() => store.clear()}>{text.clear}</button>
      </div>
      <p className="help-text assessment-submit-help">{text.submitHelp}</p>
      <button onClick={() => { void store.submit() }}>{text.submit}</button>
    </>}
    {state.kind === 'result' && <section aria-label={text.result}>
      {state.notice && <p role="status">{state.notice}</p>}
      <dl className="result-summary">
        <div><dt>{text.correctCount}</dt><dd>{state.result.correct_count}</dd></div>
        <div><dt>{text.totalCount}</dt><dd>{state.result.total_count}</dd></div>
        <div><dt>{text.percentage}</dt><dd>{formatPercentage(state.result.percentage)}</dd></div>
      </dl>
    </section>}
  </>
}

export default function AssessmentApplication(props: Props) {
  const [session] = useState(() => new SessionStore(api.auth))
  const state = useSyncExternalStore(session.subscribe, session.getSnapshot)
  const destination = assessmentDestination(props.location)
  const expired = useCallback(() => props.requireLogin(destination), [props.requireLogin, destination])
  useEffect(() => { void session.restore(); return () => session.invalidate() }, [session])
  useEffect(() => { if (state.kind === 'anonymous') expired() }, [state.kind, expired])
  return <main className="learning-shell assessment-shell">
    <nav className="learning-nav" aria-label="Навигация тестирования">
      <NavigationLink to="/" navigate={props.navigate}>{ru.home}</NavigationLink>
      <NavigationLink to="/topics" navigate={props.navigate}>{text.topics}</NavigationLink>
      <NavigationLink to="/progress" navigate={props.navigate}>{ru.progress}</NavigationLink>
      <NavigationLink to="/session" navigate={props.navigate}>{text.account}</NavigationLink>
    </nav>
    {(state.kind === 'checking' || state.kind === 'anonymous') && <p role="status">{ru.checking}</p>}
    {state.kind === 'error' && <><h1>{text.title}</h1><Notice message={ru.sessionError} />
      <button onClick={() => { void session.restore() }}>{ru.retry}</button></>}
    {state.kind === 'authenticated' && (props.location.kind === 'start' ? <StartScreen {...props} expired={expired} /> : <AttemptScreen {...props} expired={expired} />)}
  </main>
}
