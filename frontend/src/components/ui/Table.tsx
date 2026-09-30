import { type ReactNode } from 'react'

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
}: {
  children?: ReactNode
  className?: string
  /** Tooltip — used to surface a column's machine name behind its label. */
  title?: string
}) {
  return (
    <th
      title={title}
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
      className={`bg-canvas ${onClick ? 'hover:bg-canvas-subtle cursor-pointer' : ''}`}
    >
      {children}
    </tr>
  )
}

export function Td({
  children,
  className = '',
}: {
  children?: ReactNode
  className?: string
}) {
  return <td className={`px-4 py-3 text-fg ${className}`}>{children}</td>
}
