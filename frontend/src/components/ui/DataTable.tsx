import {
  useId,
  type ComponentPropsWithRef,
  type MouseEvent,
  type ReactNode,
} from 'react'
import { Link } from 'react-router'
import { ChevronUp, ChevronDown } from './icons'
import { Checkbox } from './Checkbox'
import { ErrorState, EmptyState } from './States'
import { Skeleton } from './Skeleton'

export type DataTableAlign = 'left' | 'right' | 'center'

export interface DataTableColumn<T> {
  key: string
  header: ReactNode
  /** Tooltip on the header, e.g. the machine name behind a label. */
  headerTitle?: string
  width?: string
  align?: DataTableAlign
  render?: (row: T) => ReactNode
  sortable?: boolean
  /** The `render` output is already a `<td>` (spreadsheet-style cells that
   * manage their own focus and editing). The table adds no wrapper. */
  rawCell?: boolean
  className?: string
}

export interface DataTableSort {
  key: string
  direction: 'asc' | 'desc'
}

export interface DataTableSelection {
  selected: Set<string>
  onToggle: (id: string) => void
  onToggleAll: () => void
  /** Accessible name of a row's checkbox. */
  rowLabel?: (rowId: string) => string
  allLabel?: string
}

interface DataTableProps<T> {
  columns: DataTableColumn<T>[]
  rows: T[]
  getRowId: (row: T) => string
  isLoading?: boolean
  error?: string
  emptyTitle?: string
  emptyMessage?: string
  emptyAction?: ReactNode
  /** Makes the whole row a link. The first cell holds a real `<a>` (so
   * middle-click and "open in new tab" work); a click anywhere else on the
   * row follows it too. */
  rowHref?: (row: T) => string | undefined
  /** Makes the whole row clickable. Clicks on links, buttons and inputs
   * inside the row keep doing their own thing. */
  onRowClick?: (row: T) => void
  rowClassName?: (row: T) => string
  actions?: (row: T) => ReactNode
  actionsLabel?: string
  actionsWidth?: string
  selection?: DataTableSelection
  sort?: DataTableSort
  onSortChange?: (key: string) => void
  /** Caps the table body height and enables an internal scroll container with a sticky header. */
  maxHeight?: string
  /** `fixed` (default): equal-flow columns, long text is cut off with an
   * ellipsis. `auto`: columns size to content and text wraps; the table
   * scrolls sideways if it must. */
  layout?: 'fixed' | 'auto'
  /** Extra rows after the data, e.g. a draft row for adding a record. */
  footer?: ReactNode
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
  'sticky top-0 z-10 bg-canvas-subtle border-b border-border p-0 text-xs font-medium text-fg-muted'
const thPad = 'px-4 py-3'
const INTERACTIVE = 'a, button, input, select, textarea, label, [role="button"]'

/** A body cell with the table's standard padding, for `rawCell` columns. */
export function DataTableCell({
  className = '',
  ...rest
}: ComponentPropsWithRef<'td'>) {
  return <td className={`px-4 py-3 text-fg ${className}`} {...rest} />
}

/** The one table. Header, sorting, selection, whole-row click targets,
 * loading / empty / error states, and an always-visible actions column. */
export function DataTable<T>({
  columns,
  rows,
  getRowId,
  isLoading = false,
  error,
  emptyTitle = 'No results',
  emptyMessage,
  emptyAction,
  rowHref,
  onRowClick,
  rowClassName,
  actions,
  actionsLabel = 'Actions',
  actionsWidth = '112px',
  selection,
  sort,
  onSortChange,
  maxHeight,
  layout = 'fixed',
  footer,
  className = '',
}: DataTableProps<T>) {
  const tableId = useId()
  const colCount = columns.length + (actions ? 1 : 0) + (selection ? 1 : 0)
  // Loading is handled separately: it renders skeleton rows inside this table's
  // own <tbody>, so the real header and column widths stay put. TableSkeleton
  // can't be used here — it renders its own <table>.
  const showState = !!error || (rows.length === 0 && !footer)
  const fixed = layout === 'fixed'
  const cut = fixed
    ? 'block overflow-hidden text-ellipsis whitespace-nowrap'
    : ''

  function rowActivate(row: T, e: MouseEvent<HTMLTableRowElement>) {
    const href = rowHref?.(row)
    if (href) {
      if (e.metaKey || e.ctrlKey) window.open(href, '_blank', 'noopener')
      // The row's own link does the routing, so no router hook is needed here.
      else e.currentTarget.querySelector<HTMLAnchorElement>('a[href]')?.click()
    } else onRowClick?.(row)
  }

  return (
    <div
      className={`border border-border rounded-md ${fixed ? '' : 'overflow-x-auto'} ${className}`}
    >
      <div
        className="overflow-auto rounded-md"
        style={maxHeight ? { maxHeight } : undefined}
      >
        <table
          className={`w-full border-collapse text-sm ${
            fixed ? 'table-fixed' : 'min-w-max'
          }`}
        >
          <colgroup>
            {selection && <col style={{ width: '48px' }} />}
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
              {selection && (
                <th scope="col" className={thBase}>
                  <span className="flex h-10 items-center justify-center">
                    <Checkbox
                      aria-label={selection.allLabel ?? 'Select all'}
                      checked={
                        selection.selected.size === rows.length &&
                        rows.length > 0
                      }
                      ref={(el) => {
                        if (el)
                          el.indeterminate =
                            selection.selected.size > 0 &&
                            selection.selected.size < rows.length
                      }}
                      onChange={selection.onToggleAll}
                    />
                  </span>
                </th>
              )}
              {columns.map((column) => {
                const align = column.align ?? 'left'
                const activeDirection =
                  sort && sort.key === column.key ? sort.direction : undefined
                const sortable = column.sortable && !!onSortChange
                return (
                  <th
                    key={column.key}
                    scope="col"
                    title={column.headerTitle}
                    aria-sort={
                      sortable
                        ? activeDirection === 'asc'
                          ? 'ascending'
                          : activeDirection === 'desc'
                            ? 'descending'
                            : 'none'
                        : undefined
                    }
                    className={`${thBase} ${alignClass[align]}`}
                  >
                    {sortable ? (
                      // The button fills the whole header cell.
                      <button
                        type="button"
                        onClick={() => onSortChange?.(column.key)}
                        className={`group flex w-full items-center gap-1 ${thPad} cursor-pointer hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-accent ${
                          align === 'right' ? 'flex-row-reverse' : ''
                        } ${align === 'center' ? 'justify-center' : ''}`}
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
                      <span className={`block ${thPad}`}>{column.header}</span>
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
                  {selection && <td className="px-4 py-3" />}
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
                    <EmptyState
                      title={emptyTitle}
                      message={emptyMessage}
                      action={emptyAction}
                    />
                  )}
                </td>
              </tr>
            ) : (
              <>
                {rows.map((row) => {
                  const id = getRowId(row)
                  const href = rowHref?.(row)
                  const clickable = !!href || !!onRowClick
                  return (
                    <tr
                      key={id}
                      onClick={
                        clickable
                          ? (e) => {
                              if ((e.target as Element).closest(INTERACTIVE))
                                return
                              rowActivate(row, e)
                            }
                          : undefined
                      }
                      onKeyDown={
                        onRowClick && !href
                          ? (e) => {
                              if (
                                e.target === e.currentTarget &&
                                e.key === 'Enter'
                              )
                                onRowClick(row)
                            }
                          : undefined
                      }
                      tabIndex={onRowClick && !href ? 0 : undefined}
                      className={`bg-canvas ${
                        clickable ? 'cursor-pointer hover:bg-canvas-subtle' : ''
                      } ${rowClassName?.(row) ?? ''}`}
                    >
                      {selection && (
                        <td className="px-0 py-0">
                          <span className="flex h-10 items-center justify-center">
                            <Checkbox
                              aria-label={
                                selection.rowLabel?.(id) ?? `Select ${id}`
                              }
                              checked={selection.selected.has(id)}
                              onChange={() => selection.onToggle(id)}
                            />
                          </span>
                        </td>
                      )}
                      {columns.map((column, index) => {
                        const align = column.align ?? 'left'
                        const content = column.render
                          ? column.render(row)
                          : String(
                              (row as Record<string, unknown>)[column.key] ??
                                '',
                            )
                        if (column.rawCell) return content
                        return (
                          <td
                            key={column.key}
                            className={`${index === 0 && href ? 'relative ' : ''}px-4 py-3 text-fg ${alignClass[align]} ${column.className ?? ''}`}
                          >
                            {index === 0 && href ? (
                              // A real link for keyboard, middle-click and
                              // screen readers, laid under the content so
                              // links and tooltips inside the cell still work.
                              // A click on the text reaches the row handler.
                              <>
                                <Link
                                  to={href}
                                  aria-labelledby={`${tableId}-${id}`}
                                  className="absolute inset-0 focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-accent"
                                />
                                <span
                                  id={`${tableId}-${id}`}
                                  className={`relative ${cut}`}
                                >
                                  {content}
                                </span>
                              </>
                            ) : (
                              <span className={cut}>{content}</span>
                            )}
                          </td>
                        )
                      })}
                      {actions && (
                        <td className="px-4 py-2">
                          <div className="flex items-center justify-end gap-1">
                            {actions(row)}
                          </div>
                        </td>
                      )}
                    </tr>
                  )
                })}
                {footer}
              </>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
