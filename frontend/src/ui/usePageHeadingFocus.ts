import { useEffect, useRef } from 'react'
import { PageFocus } from './focus.ts'

export function usePageHeadingFocus(ready: boolean, page: string | null = 'page') {
  const heading = useRef<HTMLHeadingElement>(null)
  const policy = useRef(new PageFocus())
  useEffect(() => { policy.current.focus(page, heading.current, ready) }, [ready, page])
  return heading
}
