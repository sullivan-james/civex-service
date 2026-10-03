import { Button } from '../ui'
import { ChevronRight } from '../ui/icons'

export interface TrailItem {
  key: string
  label: string
  /** Absent for the current scope (not a link). */
  onClick?: () => void
}

/** Where in the hierarchy the list sits: the collection (or the record the
 * page is about), then each record drilled into, then what is being listed.
 * Every step but the last goes back up to it. */
export function ScopeTrail({
  items,
  heading,
}: {
  items: TrailItem[]
  /** What is listed now, e.g. "Selection". */
  heading: string
}) {
  return (
    <nav
      aria-label="Scope"
      className="flex flex-wrap items-center gap-1 text-sm border-b border-border pb-2"
    >
      {items.map((item) => (
        <span key={item.key} className="inline-flex items-center gap-1">
          {item.onClick ? (
            <Button size="sm" variant="link" onClick={item.onClick}>
              {item.label}
            </Button>
          ) : (
            <span className="px-1 font-medium text-fg">{item.label}</span>
          )}
          <ChevronRight size={12} className="text-fg-subtle" aria-hidden />
        </span>
      ))}
      <h2 className="text-xl font-bold text-fg">{heading}</h2>
    </nav>
  )
}
