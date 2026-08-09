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
