import { useQuery } from '@tanstack/react-query'
import { analyticsApi } from '../api/analytics'
import type { AnalyticsFiltersState } from '../utils/analyticsFilters'

export function useJobStatusCounts(filters: AnalyticsFiltersState) {
  return useQuery({
    queryKey: ['analytics', 'jobs', 'status', filters],
    queryFn: () => analyticsApi.jobStatusCounts(filters),
  })
}

export function useJobDurationStats(filters: AnalyticsFiltersState) {
  return useQuery({
    queryKey: ['analytics', 'jobs', 'duration', filters],
    queryFn: () => analyticsApi.jobDurationStats(filters),
  })
}

export function usePluginFailureCounts(filters: AnalyticsFiltersState) {
  return useQuery({
    queryKey: ['analytics', 'jobs', 'failures-by-plugin', filters],
    queryFn: () => analyticsApi.pluginFailureCounts(filters),
  })
}

export function useJobTriggerBreakdown(filters: AnalyticsFiltersState) {
  return useQuery({
    queryKey: ['analytics', 'jobs', 'by-trigger', filters],
    queryFn: () => analyticsApi.jobTriggerBreakdown(filters),
  })
}

export function useAuditEventCounts(filters: AnalyticsFiltersState) {
  return useQuery({
    queryKey: ['analytics', 'audit', 'events', filters],
    queryFn: () => analyticsApi.auditEventCounts(filters),
  })
}
