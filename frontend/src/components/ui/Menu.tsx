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
  /** A line of explanation under the label, for choices that need one. */
  hint?: string
}

/** A small label that starts a group of items. */
export interface MenuHeading {
  heading: string
}

/** A rule between groups of items. */
export interface MenuSeparator {
  separator: true
}

export type MenuEntry = MenuItem | MenuHeading | MenuSeparator

/** Click-outside/Escape-to-close dropdown: a trigger element plus a list of
 * items, which can be grouped under headings and separated by rules. Shared by
 * any "more actions"-style button so the interaction is implemented once. Icons
 * all sit in the same box at the same size, so a menu's rows line up. */
export function Menu({
  trigger,
  items,
  align = 'right',
  wide = false,
}: {
  trigger: (state: { open: boolean; toggle: () => void }) => ReactNode
  items: MenuEntry[]
  align?: 'left' | 'right'
  /** For a menu whose items explain themselves with a hint line. */
  wide?: boolean
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
          className={`absolute top-full mt-1 z-40 ${wide ? 'w-80' : 'min-w-[10rem] max-w-xs'} bg-canvas border border-border rounded-md shadow-lg py-1 ${
            align === 'right' ? 'right-0' : 'left-0'
          }`}
        >
          {items.map((entry, i) => {
            if ('heading' in entry)
              return (
                <div
                  key={`heading-${i}`}
                  role="presentation"
                  className="px-3 pb-1 pt-3 text-xs font-semibold uppercase tracking-wide text-fg-subtle first:pt-2"
                >
                  {entry.heading}
                </div>
              )
            if ('separator' in entry)
              return (
                <div
                  key={`separator-${i}`}
                  role="separator"
                  className="my-1.5 border-t border-border"
                />
              )
            const danger = entry.variant === 'danger'
            return (
              <button
                key={entry.label}
                type="button"
                role="menuitem"
                disabled={entry.disabled}
                onClick={() => {
                  setOpen(false)
                  entry.onClick()
                }}
                className={`flex w-full items-center gap-3 text-left px-3 text-sm disabled:opacity-50 disabled:cursor-not-allowed ${
                  entry.hint ? 'py-2.5' : 'py-2'
                } ${
                  danger
                    ? 'text-danger hover:bg-danger-subtle'
                    : 'text-fg hover:bg-canvas-subtle'
                }`}
              >
                {entry.icon && (
                  <span
                    className={`flex h-6 w-6 shrink-0 items-center justify-center ${
                      danger ? '' : 'text-fg-muted'
                    }`}
                  >
                    <entry.icon size={18} aria-hidden="true" />
                  </span>
                )}
                {entry.hint ? (
                  <span className="flex min-w-0 flex-col">
                    <span className="font-medium">{entry.label}</span>
                    <span className="text-xs text-fg-muted">{entry.hint}</span>
                  </span>
                ) : (
                  entry.label
                )}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
