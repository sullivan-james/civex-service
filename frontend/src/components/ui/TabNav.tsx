import { useRef, type KeyboardEvent, type ReactNode } from 'react'
import { NavLink } from 'react-router'

export interface TabDef<T extends string> {
  id: T
  label: ReactNode
  /** Route tabs: the tab is a link to this path (relative to the current
   * route) and `value`/`onChange` only mark which one is current. */
  to?: string
}

type Orientation = 'horizontal' | 'vertical'

const itemBase =
  'whitespace-nowrap text-sm font-medium cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-accent'

const horizontal = (selected: boolean) =>
  `-mb-px inline-flex min-h-10 items-center border-b-2 px-4 ${
    selected
      ? 'border-accent text-fg'
      : 'border-transparent text-fg-muted hover:border-border-strong hover:text-fg'
  }`

const vertical = (selected: boolean) =>
  `flex min-h-10 items-center rounded-md px-3 ${
    selected
      ? 'bg-accent-subtle text-accent'
      : 'text-fg-muted hover:bg-canvas-subtle hover:text-fg'
  }`

/** The one navigation-between-sub-pages component. Horizontal strip for the
 * tabs of a page, vertical list for a section list (Settings). Two modes:
 *
 * - state tabs (`role="tab"`, arrow keys): give `value` + `onChange`, usually
 *   from `useTabParam`, and render the panel with `<TabPanel>`;
 * - route tabs: give each tab a `to`; they render as links and the router
 *   decides which is current.
 *
 * Every item is a full-height block, so the whole label area is clickable. */
export function TabNav<T extends string>({
  label,
  tabs,
  value,
  onChange,
  orientation = 'horizontal',
}: {
  label: string
  tabs: TabDef<T>[]
  value?: T
  onChange?: (id: T) => void
  orientation?: Orientation
}) {
  const buttons = useRef<Partial<Record<T, HTMLButtonElement | null>>>({})
  const isVertical = orientation === 'vertical'
  const style = isVertical ? vertical : horizontal
  const listClass = isVertical
    ? 'flex gap-1 overflow-x-auto md:flex-col md:overflow-visible'
    : 'flex gap-1 border-b border-border overflow-x-auto'

  if (tabs.every((t) => t.to !== undefined)) {
    return (
      <nav aria-label={label}>
        <ul className={listClass}>
          {tabs.map((tab) => (
            <li key={tab.id}>
              <NavLink
                to={tab.to as string}
                className={({ isActive }) => `${itemBase} ${style(isActive)}`}
              >
                {tab.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
    )
  }

  function onKeyDown(e: KeyboardEvent, index: number) {
    const prev = isVertical ? 'ArrowUp' : 'ArrowLeft'
    const nextKey = isVertical ? 'ArrowDown' : 'ArrowRight'
    let next: number
    if (e.key === nextKey) next = (index + 1) % tabs.length
    else if (e.key === prev) next = (index - 1 + tabs.length) % tabs.length
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = tabs.length - 1
    else return
    e.preventDefault()
    onChange?.(tabs[next].id)
    buttons.current[tabs[next].id]?.focus()
  }

  return (
    <div
      role="tablist"
      aria-label={label}
      aria-orientation={orientation}
      className={listClass}
    >
      {tabs.map((tab, i) => {
        const selected = tab.id === value
        return (
          <button
            key={tab.id}
            ref={(el) => {
              buttons.current[tab.id] = el
            }}
            type="button"
            role="tab"
            id={`tab-${tab.id}`}
            aria-selected={selected}
            aria-controls={`panel-${tab.id}`}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange?.(tab.id)}
            onKeyDown={(e) => onKeyDown(e, i)}
            className={`${itemBase} ${style(selected)}`}
          >
            {tab.label}
          </button>
        )
      })}
    </div>
  )
}

/** Panel for a state tab: wires `aria-labelledby` back to the tab and renders
 * only while that tab is selected. */
export function TabPanel<T extends string>({
  id,
  value,
  children,
}: {
  id: T
  value: T
  children: ReactNode
}) {
  if (id !== value) return null
  return (
    <div role="tabpanel" id={`panel-${id}`} aria-labelledby={`tab-${id}`}>
      {children}
    </div>
  )
}

/** @deprecated Use `TabNav`. */
export const Tabs = TabNav
