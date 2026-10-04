import type { ReactNode } from 'react'
import { Spinner } from './Spinner'

export function LoadingState() {
  return (
    <div className="flex items-center justify-center gap-2 px-6 py-16 text-sm text-fg-muted">
      <Spinner />
      Loading…
    </div>
  )
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div
      role="alert"
      className="bg-danger-subtle border border-danger-subtle-border rounded-md px-4 py-3 text-sm text-danger"
    >
      {message}
    </div>
  )
}

export function EmptyState({
  title,
  message,
  action,
}: {
  title: string
  message?: ReactNode
  /** The one thing to do next, e.g. a "New collection" button. */
  action?: ReactNode
}) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="border border-dashed border-border rounded-md px-6 py-12 text-center"
    >
      <p className="text-sm font-medium text-fg">{title}</p>
      {message && <p className="mt-1 text-sm text-fg-muted">{message}</p>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  )
}
