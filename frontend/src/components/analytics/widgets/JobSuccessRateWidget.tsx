import { useMemo } from 'react'
import { useJobStatusCounts } from '../../../hooks/useAnalytics'
import type { AnalyticsFiltersState } from '../../../utils/analyticsFilters'
import { errorMessage } from '../../../lib/errors'
import { ErrorState, EmptyState } from '../../ui'
import { jobSuccessRateSeries } from '../aggregate'
import { TimeSeriesChart } from '../TimeSeriesChart'
import { StatTile } from '../StatTile'
import { WidgetCard } from '../WidgetCard'

function formatPercent(value: number): string {
  return `${value.toFixed(0)}%`
}

export interface JobSuccessRateWidgetProps {
  filters: AnalyticsFiltersState
}

/** Job success/failure rate over time, from `WorkflowJob.status` +
 * `created_at` -- plots the completed share of settled (completed +
 * failed) runs per bucket, rather than raw counts, so the trend reads
 * independent of run volume. */
export function JobSuccessRateWidget({ filters }: JobSuccessRateWidgetProps) {
  const { data, isLoading, error } = useJobStatusCounts(filters)

  const { series, totalCompleted, totalFailed } = useMemo(
    () => jobSuccessRateSeries(data?.items ?? []),
    [data],
  )

  const settled = totalCompleted + totalFailed
  const overallRate = settled === 0 ? null : (totalCompleted / settled) * 100

  return (
    <WidgetCard
      title="Success rate"
      description="Share of completed runs, over time"
      viewRunsTo="/runs?status=failed"
      viewRunsLabel="View failed runs"
    >
      {error ? (
        <ErrorState message={errorMessage(error)} />
      ) : isLoading ? (
        <div className="flex h-[240px] items-center justify-center text-sm text-fg-muted">
          Loading…
        </div>
      ) : settled === 0 ? (
        <EmptyState
          title="No runs yet"
          message="Job outcomes will chart here once workflows run in this range."
        />
      ) : (
        <>
          <div className="flex gap-4">
            <StatTile
              label="Success rate"
              value={overallRate == null ? '—' : formatPercent(overallRate)}
            />
            <StatTile label="Failed runs" value={totalFailed} />
          </div>
          <TimeSeriesChart
            data={series}
            series={[{ key: 'rate', label: 'Success rate' }]}
            variant="area"
            formatValue={formatPercent}
          />
        </>
      )}
    </WidgetCard>
  )
}
