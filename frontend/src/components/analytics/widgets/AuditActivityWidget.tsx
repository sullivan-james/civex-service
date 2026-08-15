import { useMemo } from 'react'
import { useAuditEventCounts } from '../../../hooks/useAnalytics'
import type { AnalyticsFiltersState } from '../../../utils/analyticsFilters'
import { errorMessage } from '../../../lib/errors'
import { ErrorState, EmptyState } from '../../ui'
import { auditActivitySeries } from '../aggregate'
import { TimeSeriesChart, type TimeSeriesSeries } from '../TimeSeriesChart'
import { formatCompactNumber } from '../format'
import { WidgetCard } from '../WidgetCard'

const ACTION_LABELS: Record<string, string> = {
  create: 'Create',
  update: 'Update',
  delete: 'Delete',
  purge: 'Purge',
}

export interface AuditActivityWidgetProps {
  filters: AnalyticsFiltersState
}

/** Audit event volume over time, from `AuditLog` -- one series per action
 * (create/update/delete/purge) rather than a single combined line, so the
 * mix of activity is visible, not just its total. Responds to the shared
 * date range plus the `entityType`/`action` filters. `AuditLog` carries no
 * actor/user field, so per-user attribution isn't available here -- out of
 * scope until auth/multi-user tracking lands. */
export function AuditActivityWidget({ filters }: AuditActivityWidgetProps) {
  const { data, isLoading, error } = useAuditEventCounts(filters)

  const { series, actions, total } = useMemo(
    () => auditActivitySeries(data?.items ?? []),
    [data],
  )

  const chartSeries: TimeSeriesSeries[] = actions.map((action) => ({
    key: action,
    label: ACTION_LABELS[action] ?? action,
  }))

  return (
    <WidgetCard
      title="Activity over time"
      description="Audit events by action, this range -- no per-user breakdown (AuditLog has no actor field)"
    >
      {error ? (
        <ErrorState message={errorMessage(error)} />
      ) : isLoading ? (
        <div className="flex h-[240px] items-center justify-center text-sm text-fg-muted">
          Loading…
        </div>
      ) : total === 0 ? (
        <EmptyState
          title="No activity yet"
          message="Audit events will chart here once records, schemas, or datasets change in this range."
        />
      ) : (
        <TimeSeriesChart
          data={series}
          series={chartSeries}
          variant="line"
          formatValue={formatCompactNumber}
        />
      )}
    </WidgetCard>
  )
}
