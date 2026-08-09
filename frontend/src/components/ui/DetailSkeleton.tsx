import { Skeleton } from './Skeleton'

export function DetailSkeleton({
  metadataRows = 4,
  sections = 1,
}: {
  /** Label/value pairs in the metadata grid; 0 omits the grid entirely. */
  metadataRows?: number
  /** Number of title+body placeholder blocks below the metadata grid. */
  sections?: number
} = {}) {
  return (
    <div className="space-y-6" aria-hidden="true">
      {/* Breadcrumb */}
      <Skeleton className="h-4 w-56" />

      {/* Title + actions */}
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-2">
          <Skeleton className="h-6 w-64" />
          <Skeleton className="h-4 w-40" />
        </div>
        <Skeleton className="h-8 w-24 shrink-0" />
      </div>

      {/* Metadata grid */}
      {metadataRows > 0 && (
        <div className="grid grid-cols-2 gap-x-8 gap-y-3 border border-border rounded-md p-4 bg-canvas-subtle">
          {Array.from({ length: metadataRows }).map((_, i) => (
            <div key={i} className="space-y-1.5">
              <Skeleton className="h-3 w-16" />
              <Skeleton className="h-4 w-28" />
            </div>
          ))}
        </div>
      )}

      {/* Sections */}
      {Array.from({ length: sections }).map((_, i) => (
        <div key={i} className="space-y-2">
          <Skeleton className="h-5 w-32" />
          <Skeleton className="h-20 w-full" />
        </div>
      ))}
    </div>
  )
}
