import { useMemo } from 'react'
import { useRecordCounts } from '../../../hooks/useAnalytics'
import type { AnalyticsFiltersState } from '../../../utils/analyticsFilters'
import { errorMessage } from '../../../lib/errors'
import { ErrorState, EmptyState } from '../../ui'
import { sumRecordCountsBySchema } from '../aggregate'
import { BarBreakdown } from '../BarBreakdown'
import { formatCompactNumber } from '../format'
import { WidgetCard } from '../WidgetCard'

export interface RecordCountsWidgetProps {
  filters: AnalyticsFiltersState
}

/** Current record totals by schema, from `RecordRepository.count_by_schema`
 * -- a snapshot (not a time series), summed across datasets unless the
 * shared filter bar's `dataset` filter narrows it to one. */
export function RecordCountsWidget({ filters }: RecordCountsWidgetProps) {
  const { data, isLoading, error } = useRecordCounts(filters)

  const bars = useMemo(
    () => sumRecordCountsBySchema(data?.items ?? []),
    [data],
  )

  return (
    <WidgetCard
      title="Records by schema"
      description="Current record totals, by schema"
      viewRunsTo="/schemas"
      viewRunsLabel="View schemas"
    >
      {error ? (
        <ErrorState message={errorMessage(error)} />
      ) : isLoading ? (
        <div className="flex h-[240px] items-center justify-center text-sm text-fg-muted">
          Loading…
        </div>
      ) : bars.length === 0 ? (
        <EmptyState
          title="No records yet"
          message="Record totals will chart here once records exist."
        />
      ) : (
        <BarBreakdown
          data={bars}
          layout="vertical"
          formatValue={formatCompactNumber}
        />
      )}
    </WidgetCard>
  )
}
