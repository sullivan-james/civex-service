import { api } from './client'
import {
  toAnalyticsQueryParams,
  type AnalyticsFiltersState,
} from '../utils/analyticsFilters'

export interface JobStatusPoint {
  bucket: string
  status: string
  count: number
}

export interface JobStatusCounts {
  bucket: string
  items: JobStatusPoint[]
}

export interface DurationHistogramBin {
  label: string
  count: number
}

export interface DurationPercentileMarker {
  label: string
  bin_label: string
}

export interface JobDurationStats {
  count: number
  avg_seconds: number | null
  min_seconds: number | null
  max_seconds: number | null
  p50_seconds: number | null
  p90_seconds: number | null
  p99_seconds: number | null
  bins: DurationHistogramBin[]
  percentile_markers: DurationPercentileMarker[]
}

export interface PluginFailurePoint {
  bucket: string
  plugin: string
  count: number
}

export interface PluginFailureCounts {
  bucket: string
  items: PluginFailurePoint[]
}

export interface TriggerBreakdownPoint {
  trigger: string
  count: number
}

export interface TriggerBreakdown {
  items: TriggerBreakdownPoint[]
}

function qs(filters: AnalyticsFiltersState): string {
  return toAnalyticsQueryParams(filters).toString()
}

export const analyticsApi = {
  jobStatusCounts: (filters: AnalyticsFiltersState) =>
    api.get<JobStatusCounts>(`/analytics/jobs/status?${qs(filters)}`),
  jobDurationStats: (filters: AnalyticsFiltersState) =>
    api.get<JobDurationStats>(`/analytics/jobs/duration?${qs(filters)}`),
  pluginFailureCounts: (filters: AnalyticsFiltersState) =>
    api.get<PluginFailureCounts>(
      `/analytics/jobs/failures-by-plugin?${qs(filters)}`,
    ),
  jobTriggerBreakdown: (filters: AnalyticsFiltersState) =>
    api.get<TriggerBreakdown>(`/analytics/jobs/by-trigger?${qs(filters)}`),
}
