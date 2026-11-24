import { useState } from 'react'
import type { Navigate } from '../auth/NavigationLink.tsx'
import { NavigationLink } from '../auth/NavigationLink.tsx'
import { OverallProgress } from '../progress/OverallProgress.tsx'
import { progressRu } from '../progress/texts.ts'
import { useOverview } from './OverviewContext.tsx'
import { Button } from './Button.tsx'
import { LoadingState } from './LoadingState.tsx'

export function TopicSidebar({ navigate, topicId }: { navigate: Navigate; topicId?: string | null }) {
  const { state, reload } = useOverview()
  const [expanded, setExpanded] = useState(false)
  return <aside className="topic-sidebar" aria-label="Темы и общий прогресс">
    <h2 className="sidebar-title">Темы подготовки</h2>
    {state.kind === 'loading' && <LoadingState message={progressRu.loading} />}
    {state.kind === 'error' && <><p className="help-text">Меню тем временно недоступно.</p><Button variant="secondary" onClick={reload}>{progressRu.retry}</Button></>}
    {state.kind === 'ready' && <>
      <OverallProgress view={state.view} />
      <Button variant="secondary" className="topic-menu-toggle" aria-expanded={expanded} aria-controls="topic-menu"
        onClick={() => setExpanded(!expanded)}>Темы подготовки <span aria-hidden="true">▾</span></Button>
      <nav id="topic-menu" className={`topic-menu ${expanded ? 'is-open' : ''}`} aria-label="Выбор темы">
        {state.view.navigationTopics.length === 0 ? <p className="help-text">{progressRu.empty}</p> : <ol>
          {state.view.navigationTopics.map(topic => <li key={topic.topic_id}>
            <NavigationLink to={`/topics/${encodeURIComponent(topic.topic_id)}`} navigate={navigate}
              current={topicId === topic.topic_id ? (window.location.pathname === `/topics/${topic.topic_id}` ? 'page' : 'location') : undefined}>{topic.title}</NavigationLink>
          </li>)}
        </ol>}
      </nav>
    </>}
  </aside>
}
