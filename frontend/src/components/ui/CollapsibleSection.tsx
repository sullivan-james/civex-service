import { useState, type ReactNode } from 'react'
import { ChevronRight } from './icons'

export function CollapsibleSection({
  title,
  count,
  defaultOpen = false,
  children,
}: {
  title: string
  /** Shown next to the title, e.g. a total-entries count. */
  count?: number
  defaultOpen?: boolean
  children: ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex items-center gap-1.5 text-base font-semibold text-fg cursor-pointer select-none"
      >
        <ChevronRight
          size={16}
          className={`text-fg-muted transition-transform ${open ? 'rotate-90' : ''}`}
        />
        {title}
        {count !== undefined && (
          <span className="text-sm font-normal text-fg-muted">{count}</span>
        )}
      </button>
      {open && <div className="mt-2">{children}</div>}
    </div>
  )
}
