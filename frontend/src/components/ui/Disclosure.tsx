import { useState, type ReactNode } from 'react'
import { ChevronDown, ChevronRight } from './icons'

/** Detail that belongs to one row of a list (a job step, a tool call): the
 * whole header is the toggle. Not for structuring a page — split a big page
 * into tabs instead. */
export function Disclosure({
  summary,
  defaultOpen = false,
  children,
  className = '',
}: {
  summary: ReactNode
  defaultOpen?: boolean
  children: ReactNode
  className?: string
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div
      className={`overflow-hidden rounded-md border border-border bg-canvas ${className}`}
    >
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex min-h-10 w-full cursor-pointer items-center gap-2 px-3 py-2 text-left text-sm transition-colors hover:bg-canvas-subtle focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-accent"
      >
        {open ? (
          <ChevronDown size={14} className="shrink-0 text-fg-subtle" />
        ) : (
          <ChevronRight size={14} className="shrink-0 text-fg-subtle" />
        )}
        <span className="min-w-0 flex-1">{summary}</span>
      </button>
      {open && <div className="border-t border-border">{children}</div>}
    </div>
  )
}
