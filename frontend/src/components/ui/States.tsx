export function LoadingState({ message = 'Loading…' }: { message?: string }) {
  return (
    <div className="text-sm text-[#656d76] py-12 text-center">{message}</div>
  )
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="bg-[#ffebe9] border border-[#ffd7d5] rounded-md px-4 py-3 text-sm text-[#d1242f]">
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
    <div className="border border-dashed border-[#d0d7de] rounded-md px-6 py-16 text-center">
      <p className="text-sm font-medium text-[#1f2328]">{title}</p>
      {message && <p className="mt-1 text-sm text-[#656d76]">{message}</p>}
    </div>
  )
}
