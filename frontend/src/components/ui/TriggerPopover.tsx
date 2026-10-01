import { useState, type ReactNode } from 'react'
import { Popover } from './Popover'

/** A trigger plus a panel that opens beneath it and closes on outside click
 * or Escape. The panel is a `Popover` -- portalled and kept inside the
 * viewport -- and is only mounted while open, so its contents start fresh
 * (seeded from props) each time. */
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
  const [root, setRoot] = useState<HTMLDivElement | null>(null)
  // The trigger button itself (not its wrapper), so the panel hangs off it
  // and focus returns to it on close.
  const anchor = root?.querySelector('button') ?? root
  const close = () => setOpen(false)

  return (
    <div ref={setRoot} className="inline-flex">
      {trigger({ open, toggle: () => setOpen((o) => !o) })}
      {open && (
        <Popover
          anchor={anchor}
          onClose={close}
          label={label}
          align={align}
          minWidth={0}
          className={panelClassName}
        >
          {typeof children === 'function' ? children(close) : children}
        </Popover>
      )}
    </div>
  )
}
