export function LoadingState() {
  return (
    <div className="flex items-center justify-center gap-2 px-6 py-16 text-sm text-fg-muted">
      <svg
        className="animate-spin"
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
        aria-hidden
      >
        <path
          d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"
          strokeLinecap="round"
        />
      </svg>
      Loading…
    </div>
  )
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="bg-danger-subtle border border-danger-subtle-border rounded-md px-4 py-3 text-sm text-danger">
      {message}
    </div>
  )
}

export function EmptyState({
  title,
  message,
}: {
  title: string
  message?: string
}) {
  return (
    <div className="border border-dashed border-border rounded-md px-6 py-16 text-center">
      <p className="text-sm font-medium text-fg">{title}</p>
      {message && <p className="mt-1 text-sm text-fg-muted">{message}</p>}
    </div>
  )
}
