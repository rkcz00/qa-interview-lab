import { createContext, useContext } from 'react'
import type { ProgressState } from '../progress/model.ts'

export const OverviewContext = createContext<{ state: ProgressState; reload: () => void } | null>(null)
export function useOverview() {
  const value = useContext(OverviewContext)
  if (!value) throw new Error('Overview requires AppShell')
  return value
}
export function notifyProgressChanged() {
  window.dispatchEvent(new Event('qil-progress-changed'))
}
