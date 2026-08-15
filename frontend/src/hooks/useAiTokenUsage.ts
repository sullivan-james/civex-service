import { useQuery } from '@tanstack/react-query'
import { analyticsApi } from '../api/analytics'
import type { AnalyticsFiltersState } from '../utils/analyticsFilters'

/** `provider`/`model` null means "every value for that dimension" -- passing
 * null for both is the same query as the widget's unfiltered base fetch, so
 * TanStack Query serves it from the same cache entry instead of refetching. */
export function useAiTokenUsage(
  filters: AnalyticsFiltersState,
  provider: string | null,
  model: string | null,
) {
  return useQuery({
    queryKey: [
      'analytics',
      'ai-usage',
      filters.start,
      filters.end,
      filters.bucket,
      provider,
      model,
    ],
    queryFn: () => analyticsApi.aiTokenUsage(filters, provider, model),
  })
}
