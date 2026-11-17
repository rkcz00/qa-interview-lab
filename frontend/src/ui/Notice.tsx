import type { ComponentProps } from 'react'
import { noticeRole } from './presentation.ts'
import type { NoticeTone } from './presentation.ts'

type Props = Omit<ComponentProps<'div'>, 'role'> & { tone?: NoticeTone }

export function Notice({ tone = 'error', className = '', ...props }: Props) {
  const legacyClass = tone === 'error' ? 'form-alert' : tone === 'success' ? 'success-notice' : ''
  return <div {...props} role={noticeRole(tone)} data-tone={tone}
    className={`ui-notice ui-notice--${tone} ${legacyClass} ${className}`.trim()} />
}
