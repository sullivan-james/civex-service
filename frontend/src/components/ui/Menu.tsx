import { useRef, useState, type ComponentType, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useAnchoredPosition } from '../../hooks/useAnchoredPosition'
import { useDismiss } from '../../hooks/useDismiss'

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
 * all sit in the same box at the same size, so a menu's rows line up. The list
 * is placed like a `Popover` (`useAnchoredPosition`): against the window, above
 * the trigger when there's more room there, scrolling inside itself when it is
 * taller than that, so it never runs off the window or stretches the page. */
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
  const listRef = useRef<HTMLDivElement>(null)

  useDismiss(open, [rootRef, listRef], () => setOpen(false))
  const pos = useAnchoredPosition(rootRef, listRef, align, open)

  return (
    <div ref={rootRef} className="relative inline-flex">
      {trigger({ open, toggle: () => setOpen((o) => !o) })}
      {open &&
        createPortal(
          <div
            ref={listRef}
            role="menu"
            style={{
              position: 'fixed',
              top: pos?.top ?? 0,
              left: pos?.left ?? 0,
              maxHeight: pos?.maxHeight,
              // Invisible until measured so it never flashes at 0,0.
              visibility: pos ? 'visible' : 'hidden',
            }}
            className={`z-40 overflow-y-auto ${wide ? 'w-80' : 'min-w-[10rem] max-w-xs'} bg-canvas border border-border rounded-md shadow-lg py-1`}
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
                      <span className="text-xs text-fg-muted">
                        {entry.hint}
                      </span>
                    </span>
                  ) : (
                    entry.label
                  )}
                </button>
              )
            })}
          </div>,
          document.body,
        )}
    </div>
  )
}
