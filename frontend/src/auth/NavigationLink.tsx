import type { MouseEvent, ReactNode } from 'react'
import type { Destination } from './routing.ts'

export type Navigate = (route: Destination, replace?: boolean) => void

export function NavigationLink({ to, navigate, children }: { to: Destination; navigate: Navigate; children: ReactNode }) {
  function follow(event: MouseEvent<HTMLAnchorElement>) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    event.preventDefault()
    navigate(to)
  }
  return <a href={to} onClick={follow}>{children}</a>
}
