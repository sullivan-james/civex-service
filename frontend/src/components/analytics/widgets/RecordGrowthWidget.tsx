import { useMemo } from 'react'
import { useRecordGrowth } from '../../../hooks/useAnalytics'
import type { AnalyticsFiltersState } from '../../../utils/analyticsFilters'
import { errorMessage } from '../../../lib/errors'
import { ErrorState, EmptyState } from '../../ui'
import { recordGrowthSeries } from '../aggregate'
import { TimeSeriesChart } from '../TimeSeriesChart'
import { StatTile } from '../StatTile'
import { formatCompactNumber } from '../format'
import { WidgetCard } from '../WidgetCard'

function formatBucketLabel(value: string): string {
  const parsed = new Date(value)
  return isNaN(parsed.getTime())
    ? value
    : parsed.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export interface RecordGrowthWidgetProps {
  filters: AnalyticsFiltersState
}

/** Record creation counts over time, from `Record.created_at` -- one line
 * per dataset/schema combo left in range by the shared filter bar, so
 * narrowing to a single dataset or schema collapses it to a single trend. */
export function RecordGrowthWidget({ filters }: RecordGrowthWidgetProps) {
  const { data, isLoading, error } = useRecordGrowth(filters)

  const { series, seriesKeys, total } = useMemo(
    () => recordGrowthSeries(data?.items ?? []),
    [data],
  )

  return (
    <WidgetCard
      title="Record growth"
      description="New records over time, by dataset and schema"
      viewRunsTo="/collections"
      viewRunsLabel="View collections"
    >
      {error ? (
        <ErrorState message={errorMessage(error)} />
      ) : isLoading ? (
        <div className="flex h-[240px] items-center justify-center text-sm text-fg-muted">
          Loading…
        </div>
      ) : series.length === 0 ? (
        <EmptyState
          title="No records yet"
          message="Record creation will chart here once records are added in this range."
        />
      ) : (
        <>
          <StatTile label="New records" value={formatCompactNumber(total)} />
          <TimeSeriesChart
            data={series}
            series={seriesKeys}
            formatValue={formatCompactNumber}
            formatXAxis={formatBucketLabel}
          />
        </>
      )}
    </WidgetCard>
  )
}
