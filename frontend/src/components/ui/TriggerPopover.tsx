import { useCallback, useRef, useState, type ReactNode } from 'react'
import { useDismiss } from '../../hooks/useDismiss'

/** A trigger plus a panel that opens beneath it and closes on outside click
 * or Escape. The panel is only mounted while open, so its contents start
 * fresh (seeded from props) each time. */
export function TriggerPopover({
  trigger,
  children,
  label,
  align = 'left',
  panelClassName = '',
}: {
  trigger: (state: { open: boolean; toggle: () => void }) => ReactNode
  /** The panel's content, or a function of `close`. */
  children: ReactNode | ((close: () => void) => ReactNode)
  /** Accessible name of the panel. */
  label: string
  align?: 'left' | 'right'
  panelClassName?: string
}) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const close = useCallback(() => setOpen(false), [])
  useDismiss(open, [rootRef], close)

  return (
    <div ref={rootRef} className="relative inline-flex">
      {trigger({ open, toggle: () => setOpen((o) => !o) })}
      {open && (
        <div
          role="dialog"
          aria-label={label}
          className={`absolute top-full mt-1 z-20 bg-canvas border border-border rounded-md shadow-lg p-3 ${
            align === 'right' ? 'right-0' : 'left-0'
          } ${panelClassName}`}
        >
          {typeof children === 'function' ? children(close) : children}
        </div>
      )}
    </div>
  )
}
