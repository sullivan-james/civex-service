import { useRef, type KeyboardEvent, type ReactNode } from 'react'

export interface TabDef<T extends string> {
  id: T
  label: ReactNode
}

/** An accessible tab strip (roving tabindex, arrow keys, Home/End). It renders
 * only the strip: the caller renders the panel for the selected tab, giving it
 * `id={`panel-${id}`}` and `aria-labelledby={`tab-${id}`}`. */
export function Tabs<T extends string>({
  label,
  tabs,
  value,
  onChange,
}: {
  label: string
  tabs: TabDef<T>[]
  value: T
  onChange: (id: T) => void
}) {
  const buttons = useRef<Partial<Record<T, HTMLButtonElement | null>>>({})

  function onKeyDown(e: KeyboardEvent, index: number) {
    let next: number
    if (e.key === 'ArrowRight') next = (index + 1) % tabs.length
    else if (e.key === 'ArrowLeft')
      next = (index - 1 + tabs.length) % tabs.length
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = tabs.length - 1
    else return
    e.preventDefault()
    onChange(tabs[next].id)
    buttons.current[tabs[next].id]?.focus()
  }

  return (
    <div
      role="tablist"
      aria-label={label}
      className="flex gap-1 border-b border-border overflow-x-auto"
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
            onClick={() => onChange(tab.id)}
            onKeyDown={(e) => onKeyDown(e, i)}
            className={`-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-accent ${
              selected
                ? 'border-accent text-fg'
                : 'border-transparent text-fg-muted hover:border-border-strong hover:text-fg'
            }`}
          >
            {tab.label}
          </button>
        )
      })}
    </div>
  )
}
