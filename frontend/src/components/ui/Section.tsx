import { type ReactNode } from 'react'

/** Bordered card wrapper for a page-level content block: header bar (title,
 * optional count, optional trailing action) over a padded body. Gives
 * primary sections (Fields, Children, records table, …) the same container
 * weight the Parent/Danger-zone boxes already had, instead of floating as
 * bare headings. */
export function Section({
  title,
  count,
  action,
  children,
}: {
  title: ReactNode
  count?: number
  action?: ReactNode
  children: ReactNode
}) {
  return (
    <div className="border border-border rounded-md">
      <div className="flex items-center justify-between gap-4 border-b border-border bg-canvas-subtle rounded-t-md px-4 py-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-fg">
          {title}
          {count !== undefined && (
            <span className="text-sm font-normal text-fg-muted">{count}</span>
          )}
        </h2>
        {action}
      </div>
      <div className="p-4">{children}</div>
    </div>
  )
}
