import { useRef, type MouseEvent } from 'react'

/** Shift-click range selection for any list of checkboxes, so every list in the
 * app picks several at once the same way: click one, then shift-click another,
 * and everything between them (in the order shown) takes the state the second
 * box is going to.
 *
 * Give it the ids in the order they are drawn. Put `onClick` on each checkbox,
 * and on its label if it has one (a change event doesn't say whether shift was
 * held; the click does), and call
 * `rangeFor(id)` from its change handler: it returns the ids to set, or null for
 * an ordinary click. Either way that box becomes the start of the next range. */
/** How long a click with shift held counts for the change that follows it. */
const SHIFT_WINDOW_MS = 500

export function useRangeSelect(orderedIds: readonly string[]) {
  const anchor = useRef<string | null>(null)
  // When a click with shift held was last seen. A click on a box's *label* makes
  // the browser send a second, synthetic click to the box, which may not say
  // shift was held; it must not undo the real one, so only a shift click is
  // recorded, and it counts for a moment (long enough for both clicks and the
  // change that follows).
  const shiftAt = useRef(0)

  return {
    onClick: (e: MouseEvent) => {
      if (e.shiftKey) shiftAt.current = Date.now()
    },
    rangeFor(id: string): string[] | null {
      const from = anchor.current
      const held = Date.now() - shiftAt.current < SHIFT_WINDOW_MS
      shiftAt.current = 0
      anchor.current = id
      if (!held || from === null || from === id) return null
      const a = orderedIds.indexOf(from)
      const b = orderedIds.indexOf(id)
      // The start has scrolled away (another page, a new filter): treat it as
      // an ordinary click rather than guess.
      if (a < 0 || b < 0) return null
      return orderedIds.slice(Math.min(a, b), Math.max(a, b) + 1)
    },
  }
}

/** Apply a range to a set: every id in `ids` in (or out of) `selected`. */
export function withRange(
  selected: ReadonlySet<string>,
  ids: readonly string[],
  on: boolean,
): Set<string> {
  const next = new Set(selected)
  for (const id of ids) {
    if (on) next.add(id)
    else next.delete(id)
  }
  return next
}
