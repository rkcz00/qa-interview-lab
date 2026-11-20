import { useEffect, useState, useSyncExternalStore } from 'react'
import { api } from '../api/index.ts'
import type { Language } from '../api/types.ts'
import { NavigationLink } from '../auth/NavigationLink.tsx'
import type { Navigate } from '../auth/NavigationLink.tsx'
import { PreviewStore } from './model.ts'
import { practiceDestination } from './routing.ts'
import { practiceRu as text } from './texts.ts'

export function PracticeEntry({ topicId, language, navigate, refreshKey, expired }: {
  topicId: string; language: Language; navigate: Navigate; refreshKey?: string; expired: () => void
}) {
  const [store] = useState(() => new PreviewStore(api.practice, topicId))
  const state = useSyncExternalStore(store.subscribe, store.getSnapshot)
  useEffect(() => { void store.load(language) }, [store, language, refreshKey])
  useEffect(() => () => store.invalidate(), [store])
  useEffect(() => { if (state.kind === 'authentication') expired() }, [state.kind, expired])
  if (state.kind !== 'ready' || !state.preview) return null
  return <section className="learning-card practice-entry" aria-label={text.title}>
    {state.kind === 'ready' && <>
      <h2>{text.title}</h2>
      <NavigationLink className="ui-button ui-button--secondary" to={practiceDestination({ kind: 'preview', id: topicId, language })} navigate={navigate}>{text.entry}</NavigationLink>
    </>}
  </section>
}
