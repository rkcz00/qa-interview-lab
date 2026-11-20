import { useCallback, useEffect } from 'react'
import type { Destination } from '../auth/routing.ts'
import { BEFORE_HISTORY_NAVIGATION } from '../ui/navigation.ts'
import { practiceRu as text } from './texts.ts'

export function protectPracticeHistory(destination: Destination, confirmLeave: () => boolean) {
  const guard = (event: Event) => {
    if (window.location.pathname === destination.split('?')[0] || confirmLeave()) return
    event.preventDefault()
    window.history.pushState(null, '', destination)
  }
  window.addEventListener(BEFORE_HISTORY_NAVIGATION, guard)
  return () => window.removeEventListener(BEFORE_HISTORY_NAVIGATION, guard)
}

export function useUnsavedPractice(dirty: boolean, destination: Destination) {
  const confirmLeave = useCallback(() => !dirty || window.confirm(text.leave), [dirty])
  useEffect(() => {
    if (!dirty) return
    const unload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    const click = (event: MouseEvent) => {
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
      const anchor = event.target instanceof Element ? event.target.closest('a') : null
      if (!anchor || anchor.target === '_blank' || anchor.hasAttribute('download')) return
      const target = new URL(anchor.href)
      if (target.origin !== window.location.origin || target.pathname === window.location.pathname) return
      if (!confirmLeave()) { event.preventDefault(); event.stopPropagation() }
    }
    // The router asks synchronously, before changing React state or unmounting us.
    const releaseHistory = protectPracticeHistory(destination, confirmLeave)
    window.addEventListener('beforeunload', unload)
    document.addEventListener('click', click, true)
    return () => {
      window.removeEventListener('beforeunload', unload)
      document.removeEventListener('click', click, true)
      releaseHistory()
    }
  }, [dirty, destination, confirmLeave])
  return confirmLeave
}
