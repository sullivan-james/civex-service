import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router'
import {
  applyAnalyticsFilterPatch,
  parseAnalyticsFilters,
  type AnalyticsFiltersState,
} from '../utils/analyticsFilters'

export interface UseAnalyticsFiltersResult {
  filters: AnalyticsFiltersState
  setFilters: (patch: Partial<AnalyticsFiltersState>) => void
  resetFilters: () => void
}

/** URL-synced analytics filter state -- every widget on the analytics page
 * calls this instead of receiving filters as props, so a filter change
 * (which updates the querystring) re-renders every mounted widget without
 * prop drilling. Unset filters fall back to sensible defaults (last 30
 * days, all datasets) rather than being written into the URL, so a
 * bookmarked default view stays relative to "now" instead of freezing to
 * the date it was first opened. */
export function useAnalyticsFilters(): UseAnalyticsFiltersResult {
  const [searchParams, setSearchParams] = useSearchParams()

  const filters = useMemo(
    () => parseAnalyticsFilters(searchParams, new Date()),
    [searchParams],
  )

  const setFilters = useCallback(
    (patch: Partial<AnalyticsFiltersState>) => {
      setSearchParams((prev) => applyAnalyticsFilterPatch(prev, patch), {
        replace: true,
      })
    },
    [setSearchParams],
  )

  const resetFilters = useCallback(() => {
    setSearchParams(new URLSearchParams(), { replace: true })
  }, [setSearchParams])

  return { filters, setFilters, resetFilters }
}
