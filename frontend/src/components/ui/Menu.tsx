import { useDismiss } from '../../hooks/useDismiss'
import { useRef, useState, type ComponentType, type ReactNode } from 'react'

export interface MenuItem {
  label: string
  onClick: () => void
  icon?: ComponentType<{
    size?: number
    className?: string
    'aria-hidden'?: boolean | 'true'
  }>
  disabled?: boolean
  variant?: 'default' | 'danger'
}

/** Click-outside/Escape-to-close dropdown: a trigger element plus a list of
 * items. Shared by any "more actions"-style button so the interaction is
 * implemented once. */
export function Menu({
  trigger,
  items,
  align = 'right',
}: {
  trigger: (state: { open: boolean; toggle: () => void }) => ReactNode
  items: MenuItem[]
  align?: 'left' | 'right'
}) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

  useDismiss(open, [rootRef], () => setOpen(false))

  return (
    <div ref={rootRef} className="relative inline-flex">
      {trigger({ open, toggle: () => setOpen((o) => !o) })}
      {open && (
        <div
          role="menu"
          className={`absolute top-full mt-1 z-10 min-w-[10rem] bg-canvas border border-border rounded-md shadow-lg py-1 ${
            align === 'right' ? 'right-0' : 'left-0'
          }`}
        >
          {items.map((item) => (
            <button
              key={item.label}
              type="button"
              role="menuitem"
              disabled={item.disabled}
              onClick={() => {
                setOpen(false)
                item.onClick()
              }}
              className={`flex w-full items-center gap-2 text-left px-3 py-2 text-sm disabled:opacity-50 disabled:cursor-not-allowed ${
                item.variant === 'danger'
                  ? 'text-danger hover:bg-danger-subtle'
                  : 'text-fg hover:bg-canvas-subtle'
              }`}
            >
              {item.icon && <item.icon size={14} aria-hidden="true" />}
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
