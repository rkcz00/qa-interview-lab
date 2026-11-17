interface Props { title: string; description?: string; heading?: boolean }

export function EmptyState({ title, description, heading = false }: Props) {
  return <section className="ui-empty">
    {heading ? <h2>{title}</h2> : <p className="ui-empty-title">{title}</p>}
    {description && <p className="help-text">{description}</p>}
  </section>
}
