import { type ReactNode } from 'react'
import { Link } from 'react-router'
import { ChevronUp, ChevronDown } from './icons'
import { ErrorState, EmptyState } from './States'
import { Skeleton } from './Skeleton'

export type DataTableAlign = 'left' | 'right' | 'center'

export interface DataTableColumn<T> {
  key: string
  header: ReactNode
  width?: string
  align?: DataTableAlign
  render?: (row: T) => ReactNode
  sortable?: boolean
}

export interface DataTableSort {
  key: string
  direction: 'asc' | 'desc'
}

interface DataTableProps<T> {
  columns: DataTableColumn<T>[]
  rows: T[]
  getRowId: (row: T) => string
  isLoading?: boolean
  error?: string
  emptyTitle?: string
  emptyMessage?: string
  /** Makes rows clickable via a real `<a>` (correct keyboard/middle-click semantics), not a synthetic onClick. */
  rowHref?: (row: T) => string
  actions?: (row: T) => ReactNode
  actionsLabel?: string
  actionsWidth?: string
  sort?: DataTableSort
  onSortChange?: (key: string) => void
  /** Caps the table body height and enables an internal scroll container with a sticky header. */
  maxHeight?: string
  className?: string
}

const alignClass: Record<DataTableAlign, string> = {
  left: 'text-left',
  right: 'text-right',
  center: 'text-center',
}

/** Placeholder rows shown while loading; matches TableSkeleton's default. */
const SKELETON_ROWS = 6

const thBase =
  'sticky top-0 z-10 bg-canvas-subtle border-b border-border px-4 py-3 text-xs font-semibold text-fg-muted uppercase tracking-wider'

export function DataTable<T>({
  columns,
  rows,
  getRowId,
  isLoading = false,
  error,
  emptyTitle = 'No results',
  emptyMessage,
  rowHref,
  actions,
  actionsLabel = 'Actions',
  actionsWidth = '112px',
  sort,
  onSortChange,
  maxHeight,
  className = '',
}: DataTableProps<T>) {
  const colCount = columns.length + (actions ? 1 : 0)
  // Loading is handled separately: it renders skeleton rows inside this table's
  // own <tbody>, so the real header and column widths stay put. TableSkeleton
  // can't be used here — it renders its own <table>.
  const showState = !!error || rows.length === 0

  return (
    <div className={`border border-border rounded-md ${className}`}>
      <div
        className="overflow-auto rounded-md"
        style={maxHeight ? { maxHeight } : undefined}
      >
        <table className="w-full table-fixed border-collapse text-sm">
          <colgroup>
            {columns.map((column) => (
              <col
                key={column.key}
                style={column.width ? { width: column.width } : undefined}
              />
            ))}
            {actions && <col style={{ width: actionsWidth }} />}
          </colgroup>
          <thead>
            <tr>
              {columns.map((column) => {
                const align = column.align ?? 'left'
                const activeDirection =
                  sort && sort.key === column.key ? sort.direction : undefined
                return (
                  <th
                    key={column.key}
                    scope="col"
                    aria-sort={
                      column.sortable
                        ? activeDirection === 'asc'
                          ? 'ascending'
                          : activeDirection === 'desc'
                            ? 'descending'
                            : 'none'
                        : undefined
                    }
                    className={`${thBase} ${alignClass[align]}`}
                  >
                    {column.sortable ? (
                      <button
                        type="button"
                        onClick={() => onSortChange?.(column.key)}
                        className={`group inline-flex w-full items-center gap-1 cursor-pointer hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent rounded-sm ${
                          align === 'right'
                            ? 'flex-row-reverse justify-start'
                            : ''
                        }`}
                      >
                        {column.header}
                        {activeDirection === 'asc' ? (
                          <ChevronUp size={12} className="shrink-0" />
                        ) : activeDirection === 'desc' ? (
                          <ChevronDown size={12} className="shrink-0" />
                        ) : (
                          <ChevronDown
                            size={12}
                            className="shrink-0 opacity-0 group-hover:opacity-100"
                          />
                        )}
                      </button>
                    ) : (
                      column.header
                    )}
                  </th>
                )
              })}
              {actions && (
                <th scope="col" className={thBase}>
                  <span className="sr-only">{actionsLabel}</span>
                </th>
              )}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {isLoading ? (
              Array.from({ length: SKELETON_ROWS }).map((_, rowIndex) => (
                <tr key={`skeleton-${rowIndex}`} aria-hidden="true">
                  {columns.map((column) => (
                    <td
                      key={column.key}
                      className={`px-4 py-3 ${alignClass[column.align ?? 'left']}`}
                    >
                      <Skeleton className="h-4 w-full max-w-32" />
                    </td>
                  ))}
                  {actions && (
                    <td className="px-4 py-3">
                      <Skeleton className="h-4 w-16" />
                    </td>
                  )}
                </tr>
              ))
            ) : showState ? (
              <tr>
                <td colSpan={colCount} className="p-0">
                  {error ? (
                    <div className="px-4 py-3">
                      <ErrorState message={error} />
                    </div>
                  ) : (
                    <EmptyState title={emptyTitle} message={emptyMessage} />
                  )}
                </td>
              </tr>
            ) : (
              rows.map((row) => {
                const id = getRowId(row)
                const href = rowHref?.(row)
                return (
                  <tr
                    key={id}
                    className={`relative group bg-canvas ${href ? 'hover:bg-canvas-subtle' : ''}`}
                  >
                    {columns.map((column, index) => {
                      const align = column.align ?? 'left'
                      const content = column.render
                        ? column.render(row)
                        : String(
                            (row as Record<string, unknown>)[column.key] ?? '',
                          )
                      return (
                        <td
                          key={column.key}
                          className={`px-4 py-3 text-fg ${alignClass[align]}`}
                        >
                          {index === 0 && href ? (
                            // Truncation lives on the inner span, not this <a> or the <td> —
                            // an overflow-hidden ancestor would clip the after:inset-0 overlay
                            // that stretches the link to cover the whole row.
                            <Link
                              to={href}
                              className="static after:absolute after:inset-0 after:content-[''] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                            >
                              <span className="block overflow-hidden text-ellipsis whitespace-nowrap">
                                {content}
                              </span>
                            </Link>
                          ) : (
                            <span className="block overflow-hidden text-ellipsis whitespace-nowrap">
                              {content}
                            </span>
                          )}
                        </td>
                      )
                    })}
                    {actions && (
                      <td className="relative z-10 px-4 py-3">
                        <div className="flex items-center justify-end gap-1 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 focus-within:opacity-100 transition-opacity">
                          {actions(row)}
                        </div>
                      </td>
                    )}
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
