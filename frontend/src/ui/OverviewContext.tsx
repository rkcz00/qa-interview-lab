import { createContext, useContext } from 'react'
import type { ProgressState, ProgressStore } from '../progress/model.ts'

export const OverviewContext = createContext<{ state: ProgressState; reload: () => void; store: ProgressStore } | null>(null)
export function useOverview() {
  const value = useContext(OverviewContext)
  if (!value) throw new Error('Overview requires AppShell')
  return value
}
export function notifyProgressChanged() {
  window.dispatchEvent(new Event('qil-progress-changed'))
}
