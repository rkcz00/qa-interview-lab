import type { MouseEvent, ReactNode } from 'react'
import type { Route } from './routing.ts'

export type Navigate = (route: Route, replace?: boolean) => void

export function NavigationLink({ to, navigate, children }: { to: Route; navigate: Navigate; children: ReactNode }) {
  function follow(event: MouseEvent<HTMLAnchorElement>) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
    event.preventDefault()
    navigate(to)
  }
  return <a href={to} onClick={follow}>{children}</a>
}
