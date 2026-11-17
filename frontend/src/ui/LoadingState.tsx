export function LoadingState({ message }: { message: string }) {
  return <div className="ui-loading" role="status">
    <span className="ui-spinner" aria-hidden="true" />
    <span>{message}</span>
  </div>
}
