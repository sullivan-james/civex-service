import { type ReactNode } from 'react'
import { Link } from 'react-router'
import { ArrowRight } from '../ui/icons'

export interface WidgetCardProps {
  title: string
  description?: string
  /** Runs-view route to drill into for row-level detail, e.g.
   * `/runs?status=failed` -- widgets summarize, they don't duplicate rows. */
  viewRunsTo?: string
  viewRunsLabel?: string
  children: ReactNode
}

/** Shared frame for a dashboard widget: title, optional drill-through link
 * to the Runs view, and a content slot. Every workflow-reliability widget
 * uses this so the grid reads as one dashboard rather than four
 * differently-styled cards. */
export function WidgetCard({
  title,
  description,
  viewRunsTo,
  viewRunsLabel = 'View runs',
  children,
}: WidgetCardProps) {
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-canvas p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-fg">{title}</h3>
          {description && (
            <p className="mt-0.5 text-xs text-fg-muted">{description}</p>
          )}
        </div>
        {viewRunsTo && (
          <Link
            to={viewRunsTo}
            className="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-accent hover:underline"
          >
            {viewRunsLabel}
            <ArrowRight size={12} aria-hidden="true" />
          </Link>
        )}
      </div>
      {children}
    </div>
  )
}
