import { type ReactNode } from 'react'
import { ArrowRight } from '../ui/icons'
import { Button, Card, InfoTip } from '../ui'

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
    <Card
      title={
        <>
          {title}
          {description && <InfoTip>{description}</InfoTip>}
        </>
      }
      action={
        viewRunsTo && (
          <Button size="sm" variant="link" to={viewRunsTo}>
            {viewRunsLabel}
            <ArrowRight size={14} aria-hidden="true" />
          </Button>
        )
      }
    >
      <div className="flex flex-col gap-3">{children}</div>
    </Card>
  )
}
