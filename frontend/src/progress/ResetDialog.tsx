import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { ProgressStore, ResetState } from './model.ts'
import { progressRu as text } from './texts.ts'
import { Button } from '../ui/Button.tsx'
import { Notice } from '../ui/Notice.tsx'
import { LoadingState } from '../ui/LoadingState.tsx'

export function ResetDialog({ state, store }: { state: ResetState; store: ProgressStore }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const error = useRef<HTMLDivElement>(null)
  const cancel = useRef<HTMLButtonElement>(null)
  const [confirmed, setConfirmed] = useState(false)
  const busy = state.kind === 'posting' || state.kind === 'refreshing'
  const open = state.kind === 'confirming' || busy || (state.kind === 'error' && state.open)
  useLayoutEffect(() => {
    const element = dialog.current!
    if (open && !element.open) { setConfirmed(false); element.showModal(); cancel.current?.focus() }
    if (!open && element.open) element.close()
  }, [open])
  useEffect(() => { if (state.kind === 'error' && state.open) error.current?.focus() }, [state])
  const action = () => {
    if (state.kind === 'confirming' && confirmed) void store.confirmReset()
    else if (state.kind === 'error') void (state.action === 'retry' ? store.retryReset() : store.recoverReset())
  }
  const label = state.kind === 'posting' ? text.resetting : state.kind === 'refreshing' ? text.resetRefreshing :
    state.kind === 'error' ? (state.action === 'retry' ? text.resetRetry : state.action === 'refresh' ? text.resetRefresh : text.resetCheck) : text.reset
  return <dialog className="reset-dialog" ref={dialog} aria-labelledby="reset-title" aria-describedby="reset-warning"
    onCancel={event => { event.preventDefault(); if (!busy) store.cancelReset() }}>
    <h2 id="reset-title">{text.resetTitle}</h2>
    <p id="reset-warning">{text.resetWarning}</p>
    <form onSubmit={event => { event.preventDefault(); if (!busy) action() }}>
      {state.kind === 'confirming' && <label className="reset-agreement">
        <input type="checkbox" checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />
        <span>{text.resetAgreement}</span>
      </label>}
      {state.kind === 'error' && <Notice ref={error} tabIndex={-1}>{state.message}</Notice>}
      {busy && <LoadingState message={state.kind === 'posting' ? text.resetting : text.resetRefreshing} />}
      <div className="assessment-actions">
        <Button variant="secondary" ref={cancel} disabled={busy} onClick={store.cancelReset}>
          {state.kind === 'confirming' ? text.cancel : text.close}
        </Button>
        <Button type="submit" className="reset-confirm" busy={busy} disabled={state.kind === 'confirming' && !confirmed}>
          {label}
        </Button>
      </div>
    </form>
  </dialog>
}
