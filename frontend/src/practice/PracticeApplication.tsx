import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { api } from '../api/index.ts'
import { NavigationLink } from '../auth/NavigationLink.tsx'
import type { Navigate } from '../auth/NavigationLink.tsx'
import { AppShell } from '../ui/AppShell.tsx'
import { Button } from '../ui/Button.tsx'
import { LanguageSelector } from '../ui/LanguageSelector.tsx'
import { LoadingState } from '../ui/LoadingState.tsx'
import { Notice } from '../ui/Notice.tsx'
import { usePageHeadingFocus } from '../ui/usePageHeadingFocus.ts'
import { learningDestination } from '../learning/routing.ts'
import { PreviewStore, SubmissionStore, answerError, answerLength } from './model.ts'
import { practiceDestination } from './routing.ts'
import type { PracticeLocation } from './routing.ts'
import { practiceRu as text } from './texts.ts'
import { useUnsavedPractice } from './useUnsavedPractice.ts'

interface Props { location: PracticeLocation; navigate: Navigate; requireLogin: () => void }

function PreviewScreen({ location, navigate, requireLogin }: Props) {
  const [store] = useState(() => new PreviewStore(api.practice, location.id))
  const state = useSyncExternalStore(store.subscribe, store.getSnapshot)
  const heading = usePageHeadingFocus(!['loading', 'authentication'].includes(state.kind))
  useEffect(() => { void store.load(location.language) }, [store, location.language])
  useEffect(() => () => store.invalidate(), [store])
  useEffect(() => {
    if (state.kind === 'authentication') requireLogin()
    if (state.kind === 'started' && state.submissionId) navigate(practiceDestination({ kind: 'submission', id: state.submissionId, language: state.language }))
  }, [state.kind, state.submissionId, state.language, navigate, requireLogin])
  return <AppShell navigate={navigate} canLogout topicId={location.id}>
    <h1 ref={heading} tabIndex={-1}>{state.kind === 'not_found' ? text.notFound : text.title}</h1>
    <p><NavigationLink to={learningDestination({ topicId: location.id, language: location.language })} navigate={navigate}>{text.back}</NavigationLink></p>
    {state.kind !== 'not_found' && <LanguageSelector name="practice-language" legend={text.language} language={location.language}
      disabled={['creating', 'uncertain', 'started'].includes(state.kind)} choose={language => navigate(practiceDestination({ ...location, language }))} />}
    {state.kind === 'loading' && <LoadingState message={text.loading} />}
    {state.kind === 'not_found' && <Notice>{text.notFoundHelp}</Notice>}
    {state.kind === 'error' && <><Notice>{state.message}</Notice><Button onClick={() => { void store.load(location.language) }}>{text.retry}</Button></>}
    {state.kind === 'ready' && state.preview && <section className="learning-card">
      <h2 lang={state.language}>{state.preview.title}</h2><p>{text.intro}</p>
      {state.preview.blocked_by.map(code => <Notice key={code} tone="info">{code === 'article_not_read' ? text.readFirst : text.testFirst}</Notice>)}
      {state.message && <Notice>{state.message}</Notice>}
      <Button disabled={!state.preview.can_start} onClick={() => { void store.start() }}>{text.begin}</Button>
    </section>}
    {state.kind === 'creating' && <><LoadingState message={text.creating} /><Button busy>{text.creating}</Button></>}
    {state.kind === 'uncertain' && <><Notice>{state.message}</Notice><Button onClick={() => { void store.start(true) }}>{text.newStart}</Button></>}
  </AppShell>
}

function SubmissionScreen({ location, navigate, requireLogin }: Props) {
  const [store] = useState(() => new SubmissionStore(api.practice, location.id))
  const state = useSyncExternalStore(store.subscribe, store.getSnapshot)
  const [confirming, setConfirming] = useState(false)
  const answer = useRef<HTMLTextAreaElement>(null)
  const messageBox = useRef<HTMLDivElement>(null)
  const confirmButton = useRef<HTMLButtonElement>(null)
  const removeButton = useRef<HTMLButtonElement>(null)
  const cancelled = useRef(false)
  const pending = state.item?.status === 'in_progress' ? state.item : null
  const result = state.item?.status === 'submitted' ? state.item : null
  const heading = usePageHeadingFocus(state.kind === 'ready' || state.kind === 'result' || state.kind === 'not_found', state.kind === 'result' ? 'result' : 'practice')
  const dirty = Boolean(pending && (state.answer.length > 0 || ['sending', 'uncertain', 'checking'].includes(state.kind)))
  const confirmLeave = useUnsavedPractice(dirty, practiceDestination(location))
  const problem = answerError(state.answer)
  const count = answerLength(state.answer)
  useEffect(() => { void store.load(location.language) }, [store, location.language])
  useEffect(() => () => store.invalidate(), [store])
  useEffect(() => {
    if (state.kind === 'authentication') requireLogin()
    if (state.kind === 'deleted') navigate(state.deletedTopic ? practiceDestination({ kind: 'preview', id: state.deletedTopic, language: location.language }) : '/', true)
    if (state.kind === 'restarted' && state.nextSubmission) navigate(practiceDestination({ kind: 'submission', ...state.nextSubmission }))
  }, [state.kind, state.deletedTopic, state.nextSubmission, requireLogin, navigate, location.language])
  useEffect(() => {
    if (['ready', 'result', 'restart_uncertain'].includes(state.kind) && state.message) {
      if (state.fieldError) answer.current?.focus()
      else messageBox.current?.focus()
    }
  }, [state.kind, state.message, state.fieldError])
  useEffect(() => {
    if (confirming) confirmButton.current?.focus()
    else if (cancelled.current) { cancelled.current = false; removeButton.current?.focus() }
  }, [confirming])
  const back = useCallback(() => {
    const topicId = state.item?.topic_id
    return topicId ? learningDestination({ topicId, language: location.language }) : '/'
  }, [state.item?.topic_id, location.language])
  return <AppShell navigate={navigate} canLogout topicId={state.item?.topic_id} beforeLogout={confirmLeave}>
    <h1 ref={heading} tabIndex={-1}>{state.kind === 'not_found' ? text.notFound : result ? text.result : text.title}</h1>
    <p><NavigationLink to={back()} navigate={navigate}>{state.item ? text.back : text.catalog}</NavigationLink></p>
    {!result && state.kind !== 'not_found' && <LanguageSelector name="practice-language" legend={text.language} language={location.language}
      disabled={!['ready', 'loading', 'error'].includes(state.kind)} choose={language => navigate(practiceDestination({ ...location, language }))} />}
    {['loading', 'authentication'].includes(state.kind) && <LoadingState message={text.loading} />}
    {state.kind === 'not_found' && <Notice>{text.notFoundHelp}</Notice>}
    {state.message && <Notice id="practice-message" ref={messageBox} tabIndex={-1}>{state.message}</Notice>}
    {state.kind === 'error' && <Button variant="secondary" onClick={() => { void store.load(location.language) }}>{text.retry}</Button>}
    {pending && ['ready', 'loading', 'sending', 'error'].includes(state.kind) && <section className="learning-card practice-task">
      <h2 lang={pending.language}>{pending.task.title}</h2>
      <p className="practice-content" lang={pending.language}>{pending.task.prompt}</p>
      <h3>{text.source}</h3><pre className="practice-source"><code>{pending.task.source_text}</code></pre>
      <h3>{text.input}</h3><pre className="practice-source">{pending.task.input_data || text.noInput}</pre>
      <h3>{text.environment}</h3><p className="practice-content">{pending.task.environment}</p>
      <h3>{text.output}</h3><p className="practice-content">{pending.task.output_spec}</p>
      <Notice tone="info">{pending.task.normalization_mode === 'lf_exact_v1' ? text.exact : text.trim}</Notice>
      <form className="practice-form" noValidate onSubmit={event => { event.preventDefault(); void store.submit() }}>
        <label htmlFor="practice-answer">{text.answer}</label>
        <textarea id="practice-answer" ref={answer} value={state.answer} rows={7} spellCheck={false} autoCapitalize="off" autoComplete="off"
          disabled={state.kind !== 'ready'} aria-describedby={'practice-input-help practice-count practice-input-error' + (state.message ? ' practice-message' : '')}
          aria-invalid={Boolean(problem || state.fieldError)} onChange={event => store.setAnswer(event.currentTarget.value)} />
        <p id="practice-input-help" className="help-text">{text.inputHelp}</p>
        <p id="practice-count" className="help-text" aria-live="polite">{count} / 5000</p>
        <p id="practice-input-error" className="help-text" role={problem ? 'alert' : undefined}>{problem}</p>
        <Button type="submit" busy={state.kind === 'sending'} disabled={state.kind !== 'ready' || Boolean(problem)}>{state.kind === 'sending' ? text.sending : text.submit}</Button>
      </form>
    </section>}
    {state.kind === 'checking' && <LoadingState message={text.checking} />}
    {(state.kind === 'uncertain' || state.kind === 'delete_uncertain') && <div className="assessment-actions">
      <Button variant="secondary" onClick={() => { void (state.kind === 'delete_uncertain' ? store.checkDelete() : store.check()) }}>{text.check}</Button>
      {state.canRetry && <Button onClick={() => { void (state.kind === 'delete_uncertain' ? store.retryDelete() : store.retrySame()) }}>{state.kind === 'delete_uncertain' ? text.retryDelete : text.retrySame}</Button>}
    </div>}
    {['result', 'restarting', 'restart_uncertain', 'restarted'].includes(state.kind) && result && <section className="learning-card practice-result" aria-label={text.result}>
      <h2 lang={result.submitted_language}>{result.task_title}</h2>
      <Notice tone={result.result.verdict === 'correct' ? 'success' : 'error'}>{result.result.verdict === 'correct' ? text.correct : text.incorrect}</Notice>
    </section>}
    {state.kind === 'restarting' && <><LoadingState message={text.restarting} /><Button busy>{text.restarting}</Button></>}
    {state.kind === 'restart_uncertain' && <Button onClick={() => { void store.restart(true) }}>{text.newStart}</Button>}
    {state.kind === 'deleting' && <LoadingState message={text.removing} />}
    {['ready', 'result'].includes(state.kind) && !confirming && <div className="assessment-actions">
      {result && <Button disabled={state.restartBlocked} onClick={() => { void store.restart() }}>{text.restart}</Button>}
      <Button ref={removeButton} variant="secondary" onClick={() => setConfirming(true)}>{result ? text.removeResult : text.remove}</Button>
    </div>}
    {confirming && ['ready', 'result'].includes(state.kind) && <section className="learning-card" aria-label={text.confirmTitle}>
      <h2>{text.confirmTitle}</h2><p>{text.confirmHelp}</p><div className="assessment-actions">
        <Button ref={confirmButton} onClick={() => { setConfirming(false); void store.remove(true) }}>{text.confirmRemove}</Button>
        <Button variant="secondary" onClick={() => { cancelled.current = true; setConfirming(false) }}>{text.cancel}</Button>
      </div>
    </section>}
  </AppShell>
}

export default function PracticeApplication(props: Props) {
  return props.location.kind === 'preview' ? <PreviewScreen {...props} /> : <SubmissionScreen {...props} />
}
