import { type ReactNode } from 'react'

/** A heading for a block inside a page or panel (one level below a card
 * title). The one place that decides how those look. */
export function Subheading({
  children,
  as: Tag = 'h3',
  className = '',
}: {
  children: ReactNode
  as?: 'h2' | 'h3' | 'h4' | 'span'
  className?: string
}) {
  return (
    <Tag
      className={`flex items-center gap-1 text-sm font-semibold text-fg ${className}`}
    >
      {children}
    </Tag>
  )
}
