import { useRef, type KeyboardEvent, type ReactNode } from 'react'
import { useStored } from '../../hooks/useStored'

/** Two panes side by side with a divider to drag: the main one, and a side
 * one whose width is kept per browser and project. The divider takes the
 * arrow keys (Home and End: narrowest and widest). On a narrow screen the
 * panes stack, main first, and there is no divider. With no `side` the main
 * pane has the whole width. */
export function SplitPane({
  main,
  side,
  storageKey,
  label,
  initial = 340,
  min = 260,
  max = 760,
}: {
  main: ReactNode
  side?: ReactNode
  /** Where the width is remembered. */
  storageKey: string
  /** What the divider resizes, for a screen reader ("Charts"). */
  label: string
  initial?: number
  min?: number
  max?: number
}) {
  const [width, setWidth] = useStored(storageKey, initial)
  const drag = useRef<{ x: number; width: number } | null>(null)
  const clamp = (w: number) => Math.round(Math.min(max, Math.max(min, w)))
  const shown = clamp(width)

  function onKeyDown(e: KeyboardEvent) {
    // The side pane is on the right: left makes it wider.
    const step = e.shiftKey ? 64 : 16
    if (e.key === 'ArrowLeft') setWidth(clamp(shown + step))
    else if (e.key === 'ArrowRight') setWidth(clamp(shown - step))
    else if (e.key === 'Home') setWidth(min)
    else if (e.key === 'End') setWidth(max)
    else return
    e.preventDefault()
  }

  if (!side) return <div className="min-w-0">{main}</div>
  return (
    <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:gap-0">
      <div className="min-w-0 flex-1">{main}</div>
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label={`Resize ${label}`}
        aria-valuenow={shown}
        aria-valuemin={min}
        aria-valuemax={max}
        tabIndex={0}
        onKeyDown={onKeyDown}
        onPointerDown={(e) => {
          drag.current = { x: e.clientX, width: shown }
          e.currentTarget.setPointerCapture?.(e.pointerId)
        }}
        onPointerMove={(e) => {
          if (drag.current)
            setWidth(clamp(drag.current.width + drag.current.x - e.clientX))
        }}
        onPointerUp={() => (drag.current = null)}
        className="hidden w-4 shrink-0 cursor-col-resize self-stretch lg:flex lg:justify-center focus-visible:outline-2 focus-visible:outline-accent"
      >
        <span className="w-px self-stretch bg-border" />
      </div>
      <div
        className="min-w-0 shrink-0 lg:w-[var(--side)]"
        style={{ ['--side' as string]: `${shown}px` }}
      >
        {side}
      </div>
    </div>
  )
}
