import { useState } from 'react'
import type { DataTableSelection } from '../components/ui/DataTable'
import { withRange } from './useRangeSelect'

/** The ticks on a paged list, as the records explorer and the Files tab both
 * have them: rows ticked one by one or a shift-click range, the page box
 * (ticking the page, or clearing everything when anything is ticked), and
 * "all N matching" -- every row the list's filters match, on every page, for a
 * bulk action -- which the page box also clears. Cleared whenever `resetKey`
 * changes (another filter, page or scope: different rows). */
export function useBulkSelection(rowIds: string[], resetKey: string) {
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [allMatching, setAllMatching] = useState(false)
  const [seenKey, setSeenKey] = useState(resetKey)
  if (resetKey !== seenKey) {
    setSeenKey(resetKey)
    setSelected(new Set())
    setAllMatching(false)
  }
  const clear = () => {
    setSelected(new Set())
    setAllMatching(false)
  }
  // With "all matching", every row on screen shows ticked.
  const shown = allMatching ? new Set(rowIds) : selected
  const table: DataTableSelection = {
    selected: shown,
    onToggle: (id) => {
      setAllMatching(false)
      setSelected(() => {
        const next = new Set(shown)
        if (!next.delete(id)) next.add(id)
        return next
      })
    },
    onSetMany: (ids, on) => {
      setAllMatching(false)
      setSelected(withRange(shown, ids, on))
    },
    onToggleAll: () => {
      const anything = allMatching || selected.size > 0
      setAllMatching(false)
      setSelected(
        anything && (allMatching || selected.size === rowIds.length)
          ? new Set()
          : new Set(rowIds),
      )
    },
  }
  return {
    /** The rows ticked one by one (empty meaning nothing, unless
     * `allMatching`). */
    selected,
    allMatching,
    selectAllMatching: () => setAllMatching(true),
    clear,
    /** For `DataTable`'s `selection`. */
    table,
    /** How many a bulk action covers. */
    count: (total: number) => (allMatching ? total : selected.size),
  }
}
