import { useEffect, useRef } from 'react'

export function observeArticleEnd(currentTarget: () => HTMLSpanElement | null, onRead: () => void) {
  let observed = currentTarget()
  if (!observed || typeof IntersectionObserver === 'undefined') return
  let saved = false
  const observer = new IntersectionObserver(entries => {
    if (saved || document.visibilityState !== 'visible') return
    const target = currentTarget()
    if (!target?.isConnected || !entries.some(entry => entry.target === target && entry.isIntersecting && entry.intersectionRatio >= 1)) return
    const box = target.getBoundingClientRect()
    if (box.width <= 0 || box.height <= 0 || box.top < 0 || box.bottom > window.innerHeight || box.left < 0 || box.right > window.innerWidth) return
    if (typeof target.checkVisibility === 'function' && !target.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return
    saved = true
    onRead()
  }, { threshold: 1 })
  const refresh = () => {
    if (saved || document.visibilityState !== 'visible') return
    // A translation or Suspense may have replaced or hidden the previous marker.
    if (observed) observer.unobserve(observed)
    observer.takeRecords()
    observed = currentTarget()
    if (observed) observer.observe(observed)
  }
  observer.observe(observed)
  document.addEventListener('visibilitychange', refresh)
  return () => { saved = true; observer.disconnect(); document.removeEventListener('visibilitychange', refresh) }
}

export function useAutomaticRead(enabled: boolean, onRead: () => void) {
  const end = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    if (enabled) return observeArticleEnd(() => end.current, onRead)
  }, [enabled, onRead])
  return end
}
