import { api } from './client'
import { toAnalyticsQueryParams } from '../utils/analyticsFilters'
import type { AnalyticsFiltersState } from '../utils/analyticsFilters'

export interface TokenUsageBucket {
  bucket: string
  provider: string
  model: string
  input_tokens: number
  output_tokens: number
}

export interface AiTokenUsageResponse {
  bucket: string
  items: TokenUsageBucket[]
}

export const analyticsApi = {
  /** AI provider token usage over time, broken out by provider and model.
   * `provider`/`model` narrow to a single provider/model -- omit either to
   * include every value for that dimension. */
  aiTokenUsage: (
    filters: AnalyticsFiltersState,
    provider?: string | null,
    model?: string | null,
  ) => {
    const params = toAnalyticsQueryParams(filters)
    if (provider) params.set('provider', provider)
    if (model) params.set('model', model)
    return api.get<AiTokenUsageResponse>(`/analytics/ai/usage?${params}`)
  },
}
