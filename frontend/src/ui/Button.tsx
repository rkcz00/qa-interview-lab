import type { ComponentProps } from 'react'
import { buttonState } from './presentation.ts'

type Props = ComponentProps<'button'> & { variant?: 'primary' | 'secondary'; busy?: boolean }

export function Button({ type = 'button', variant = 'primary', busy = false, disabled = false, className = '', ...props }: Props) {
  const state = buttonState(disabled, busy)
  return <button {...props} type={type} disabled={state.disabled} aria-busy={state.ariaBusy}
    data-busy={state.busy || undefined} className={`ui-button ui-button--${variant} ${className}`.trim()} />
}
