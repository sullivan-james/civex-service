import { useMemo } from 'react'
import { usePluginFailureCounts } from '../../../hooks/useAnalytics'
import type { AnalyticsFiltersState } from '../../../utils/analyticsFilters'
import { errorMessage } from '../../../lib/errors'
import { ErrorState, EmptyState } from '../../ui'
import { sumFailuresByPlugin } from '../aggregate'
import { BarBreakdown } from '../BarBreakdown'
import { formatCompactNumber } from '../format'
import { WidgetCard } from '../WidgetCard'

export interface PluginFailuresWidgetProps {
  filters: AnalyticsFiltersState
}

/** Failed step-execution counts by plugin, over the filtered date range --
 * generalizes `civex worker stats`' all-time aggregate the same way the
 * backing endpoint does. Buckets are summed client-side since the widget
 * cares about "which plugin fails most", not a per-bucket trend. */
export function PluginFailuresWidget({ filters }: PluginFailuresWidgetProps) {
  const { data, isLoading, error } = usePluginFailureCounts(filters)

  const bars = useMemo(() => sumFailuresByPlugin(data?.items ?? []), [data])

  return (
    <WidgetCard
      title="Failures by plugin"
      description="Failed step executions, this range"
      viewRunsTo="/runs?status=failed"
      viewRunsLabel="View failed runs"
    >
      {error ? (
        <ErrorState message={errorMessage(error)} />
      ) : isLoading ? (
        <div className="flex h-[240px] items-center justify-center text-sm text-fg-muted">
          Loading…
        </div>
      ) : bars.length === 0 ? (
        <EmptyState
          title="No failures"
          message="No step executions failed in this range."
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
