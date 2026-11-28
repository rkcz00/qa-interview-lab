import { createContext, useContext } from 'react'
import type { SectionReads } from './reading.ts'

export const ReadingContext = createContext<SectionReads | null>(null)
export function useSectionReads() {
  const value = useContext(ReadingContext)
  if (!value) throw new Error('Reading requires its session registry')
  return value
}
