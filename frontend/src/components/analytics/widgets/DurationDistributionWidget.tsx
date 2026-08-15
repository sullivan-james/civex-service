import { useMemo } from 'react'
import { useJobDurationStats } from '../../../hooks/useAnalytics'
import type { AnalyticsFiltersState } from '../../../utils/analyticsFilters'
import { errorMessage } from '../../../lib/errors'
import { ErrorState, EmptyState } from '../../ui'
import {
  DurationHistogram,
  type DurationHistogramPercentile,
} from '../DurationHistogram'
import { StatTile } from '../StatTile'
import { formatDurationSeconds } from '../format'
import { WidgetCard } from '../WidgetCard'

export interface DurationDistributionWidgetProps {
  filters: AnalyticsFiltersState
}

function stat(seconds: number | null): string {
  return seconds == null ? '—' : formatDurationSeconds(seconds)
}

/** Job/step duration distribution, from `StepExecution.duration_seconds` --
 * a histogram plus p50/p90/p99 markers, not just a mean, so a widening
 * tail is visible even while the average looks fine. */
export function DurationDistributionWidget({
  filters,
}: DurationDistributionWidgetProps) {
  const { data, isLoading, error } = useJobDurationStats(filters)

  const percentiles = useMemo<DurationHistogramPercentile[]>(
    () =>
      (data?.percentile_markers ?? []).map((m) => ({
        label: m.label,
        binLabel: m.bin_label,
      })),
    [data],
  )

  return (
    <WidgetCard
      title="Step duration"
      description="Distribution of step execution times"
      viewRunsTo="/runs"
    >
      {error ? (
        <ErrorState message={errorMessage(error)} />
      ) : isLoading ? (
        <div className="flex h-[240px] items-center justify-center text-sm text-fg-muted">
          Loading…
        </div>
      ) : !data || data.count === 0 ? (
        <EmptyState
          title="No step executions"
          message="Duration stats will chart here once workflow steps run in this range."
        />
      ) : (
        <>
          <div className="flex gap-4">
            <StatTile label="p50" value={stat(data.p50_seconds)} />
            <StatTile label="p90" value={stat(data.p90_seconds)} />
            <StatTile label="p99" value={stat(data.p99_seconds)} />
          </div>
          <DurationHistogram bins={data.bins} percentiles={percentiles} />
        </>
      )}
    </WidgetCard>
  )
}
