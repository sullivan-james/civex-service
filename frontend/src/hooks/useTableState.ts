import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router'
import {
  applyTablePatch,
  parseTableState,
  type TableState,
} from '../utils/tableState'

/** A filterable table's search, filter, sort and paging, held in the address
 * so a table is linkable and Back undoes a refinement. `ns` keeps two tables
 * (or a table under a tab) apart. Refining replaces the history entry: it is
 * the same list, not a new place. */
export function useTableState(ns = '', defaultPageSize = 25) {
  const [searchParams, setSearchParams] = useSearchParams()
  const state = useMemo(
    () => parseTableState(searchParams, ns, defaultPageSize),
    [searchParams, ns, defaultPageSize],
  )
  const patch = useCallback(
    (p: Partial<TableState>) =>
      setSearchParams((prev) => applyTablePatch(prev, p, ns, defaultPageSize), {
        replace: true,
      }),
    [setSearchParams, ns, defaultPageSize],
  )
  return { state, patch }
}
