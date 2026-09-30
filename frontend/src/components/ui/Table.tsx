import { type ComponentPropsWithRef, type ReactNode } from 'react'

export function Table({
  children,
  className = '',
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <div
      className={`border border-border rounded-md overflow-x-auto ${className}`}
    >
      <table className="w-full min-w-max text-sm border-collapse">
        {children}
      </table>
    </div>
  )
}

export function Thead({ children }: { children: ReactNode }) {
  return (
    <thead className="bg-canvas-subtle border-b border-border">
      {children}
    </thead>
  )
}

export function Th({
  children,
  className = '',
  title,
  sortDirection,
}: {
  children?: ReactNode
  className?: string
  /** Set on a sortable column: the current direction, or `'none'`. Lives on
   * the header cell (not the inner button) — that's where assistive tech
   * reads `aria-sort`. Omit for non-sortable columns. */
  sortDirection?: 'asc' | 'desc' | 'none'
  /** Tooltip — used to surface a column's machine name behind its label. */
  title?: string
}) {
  return (
    <th
      scope="col"
      title={title}
      aria-sort={
        sortDirection === undefined
          ? undefined
          : sortDirection === 'asc'
            ? 'ascending'
            : sortDirection === 'desc'
              ? 'descending'
              : 'none'
      }
      className={`px-4 py-3 text-left text-xs font-semibold text-fg-muted uppercase tracking-wider ${className}`}
    >
      {children}
    </th>
  )
}

export function Tbody({ children }: { children: ReactNode }) {
  return <tbody className="divide-y divide-border">{children}</tbody>
}

export function Tr({
  children,
  onClick,
}: {
  children: ReactNode
  onClick?: () => void
}) {
  return (
    <tr
      onClick={onClick}
      // Keyboard parity for the click handler; only when the row itself has
      // focus so Enter on a nested link/button doesn't fire it twice.
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={
        onClick
          ? (e) => {
              if (e.target === e.currentTarget && e.key === 'Enter') onClick()
            }
          : undefined
      }
      className={`bg-canvas ${onClick ? 'hover:bg-canvas-subtle cursor-pointer' : ''}`}
    >
      {children}
    </tr>
  )
}

export function Td({
  children,
  className = '',
  ...rest
}: ComponentPropsWithRef<'td'>) {
  return (
    <td className={`px-4 py-3 text-fg ${className}`} {...rest}>
      {children}
    </td>
  )
}
