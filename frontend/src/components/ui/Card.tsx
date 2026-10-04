import { Link } from 'react-router'
import { type ReactNode } from 'react'

type Variant = 'static' | 'interactive' | 'danger'

const surface = 'border rounded-lg bg-canvas'
const variants: Record<Variant, string> = {
  static: 'border-border',
  interactive:
    'border-border transition-colors hover:bg-canvas-subtle hover:border-border-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent',
  danger: 'border-danger-subtle-border',
}

export interface CardProps {
  /** `interactive` makes the whole card the click target (needs `to` or
   * `onClick`). `danger` marks destructive zones. */
  variant?: Variant
  title?: ReactNode
  /** Shown beside the title, e.g. a total. */
  count?: number
  /** Trailing header content (buttons, a menu). Not part of the click target
   * of an interactive card. */
  action?: ReactNode
  /** Router destination: renders the whole card as a link. */
  to?: string
  onClick?: () => void
  /** For a card that chooses one of several options. */
  selected?: boolean
  /** Drop the body padding for content that brings its own (tables). */
  flush?: boolean
  className?: string
  children?: ReactNode
}

/** The one bordered container: a section of a page, a dashboard tile, a
 * clickable shortcut, a danger zone. */
export function Card({
  variant,
  title,
  count,
  action,
  to,
  onClick,
  selected,
  flush = false,
  className = '',
  children,
}: CardProps) {
  const kind: Variant = variant ?? (to || onClick ? 'interactive' : 'static')
  const classes = `${surface} ${
    selected ? 'border-accent bg-accent-subtle' : variants[kind]
  } ${className}`

  const header =
    title !== undefined || action ? (
      <div
        className={`flex min-h-12 items-center justify-between gap-4 px-4 py-2 ${
          children ? 'border-b border-border' : ''
        }`}
      >
        <h2 className="flex items-center gap-2 text-base font-semibold text-fg">
          {title}
          {count !== undefined && (
            <span className="text-sm font-normal text-fg-muted">{count}</span>
          )}
        </h2>
        {action}
      </div>
    ) : null
  const body = children ? (
    <div className={flush ? '' : 'p-4'}>{children}</div>
  ) : null

  if (to) {
    return (
      <Link to={to} className={`block ${classes}`}>
        {header}
        {body}
      </Link>
    )
  }
  if (onClick) {
    return (
      <button
        type="button"
        aria-pressed={selected}
        onClick={onClick}
        className={`block w-full cursor-pointer text-left ${classes}`}
      >
        {header}
        {body}
      </button>
    )
  }
  return (
    <section className={classes}>
      {header}
      {body}
    </section>
  )
}
