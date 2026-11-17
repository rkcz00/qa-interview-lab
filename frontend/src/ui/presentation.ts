export type NoticeTone = 'error' | 'success' | 'info'

export function buttonState(disabled = false, busy = false) {
  return { disabled: disabled || busy, busy, ariaBusy: busy ? true as const : undefined }
}

export function noticeRole(tone: NoticeTone) {
  return tone === 'error' ? 'alert' as const : 'status' as const
}
