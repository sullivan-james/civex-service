import { useMemo } from 'react'
import { useJobTriggerBreakdown } from '../../../hooks/useAnalytics'
import type { AnalyticsFiltersState } from '../../../utils/analyticsFilters'
import { errorMessage } from '../../../lib/errors'
import { ErrorState, EmptyState } from '../../ui'
import { BarBreakdown, type BarBreakdownDatum } from '../BarBreakdown'
import { formatCompactNumber } from '../format'
import { WidgetCard } from '../WidgetCard'

const TRIGGER_LABELS: Record<string, string> = {
  record_created: 'Record created',
  record_updated: 'Record updated',
  manual: 'Manual',
}

export interface TriggerBreakdownWidgetProps {
  filters: AnalyticsFiltersState
}

/** Job counts broken out by trigger type (record_created / record_updated /
 * manual), over the filtered range -- a snapshot, not a time series. */
export function TriggerBreakdownWidget({
  filters,
}: TriggerBreakdownWidgetProps) {
  const { data, isLoading, error } = useJobTriggerBreakdown(filters)

  const bars = useMemo<BarBreakdownDatum[]>(
    () =>
      (data?.items ?? [])
        .filter((item) => item.count > 0)
        .map((item) => ({
          label: TRIGGER_LABELS[item.trigger] ?? item.trigger,
          value: item.count,
        })),
    [data],
  )

  return (
    <WidgetCard
      title="Runs by trigger"
      description="How runs were started, this range"
      viewRunsTo="/runs"
    >
      {error ? (
        <ErrorState message={errorMessage(error)} />
      ) : isLoading ? (
        <div className="flex h-[240px] items-center justify-center text-sm text-fg-muted">
          Loading…
        </div>
      ) : bars.length === 0 ? (
        <EmptyState
          title="No runs yet"
          message="Trigger breakdown will chart here once workflows run in this range."
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
