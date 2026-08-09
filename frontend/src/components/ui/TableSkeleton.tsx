import { Skeleton } from './Skeleton'

const DEFAULT_COLUMNS = ['w-32', 'w-24', 'w-40', 'w-20']

export function TableSkeleton({
  columns = DEFAULT_COLUMNS,
  rows = 6,
  bordered = true,
}: {
  /** One tailwind width class per column, sized to approximate real content. */
  columns?: string[]
  rows?: number
  /** Match the bordered `<Table>` chrome, or a borderless row-divided table. */
  bordered?: boolean
}) {
  const table = (
    <table className="w-full text-sm border-collapse" aria-hidden="true">
      <thead
        className={bordered ? 'bg-canvas-subtle border-b border-border' : ''}
      >
        <tr className={bordered ? '' : 'border-b border-border'}>
          {columns.map((_, i) => (
            <th key={i} className="px-4 py-2.5 text-left">
              <Skeleton className="h-3 w-16" />
            </th>
          ))}
        </tr>
      </thead>
      <tbody className={bordered ? 'divide-y divide-border' : ''}>
        {Array.from({ length: rows }).map((_, r) => (
          <tr key={r} className={bordered ? '' : 'border-b border-border'}>
            {columns.map((width, c) => (
              <td key={c} className="px-4 py-3">
                <Skeleton className={`h-4 ${width}`} />
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )

  if (!bordered) return table

  return (
    <div className="border border-border rounded-md overflow-hidden">
      {table}
    </div>
  )
}
