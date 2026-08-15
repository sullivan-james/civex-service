import { useMemo } from 'react'
import { useAuditEventCounts } from '../../../hooks/useAnalytics'
import type { AnalyticsFiltersState } from '../../../utils/analyticsFilters'
import { errorMessage } from '../../../lib/errors'
import { ErrorState, EmptyState } from '../../ui'
import { sumAuditByEntityType } from '../aggregate'
import { BarBreakdown } from '../BarBreakdown'
import { formatCompactNumber } from '../format'
import { WidgetCard } from '../WidgetCard'

export interface AuditEntityBreakdownWidgetProps {
  filters: AnalyticsFiltersState
}

/** Audit event counts by entity_type (record/schema/field/dataset), summed
 * over the filtered range -- a snapshot, not a time series. Responds to the
 * shared date range plus the `entityType`/`action` filters. */
export function AuditEntityBreakdownWidget({
  filters,
}: AuditEntityBreakdownWidgetProps) {
  const { data, isLoading, error } = useAuditEventCounts(filters)

  const bars = useMemo(() => sumAuditByEntityType(data?.items ?? []), [data])

  return (
    <WidgetCard
      title="Activity by entity type"
      description="What's changing most, this range"
    >
      {error ? (
        <ErrorState message={errorMessage(error)} />
      ) : isLoading ? (
        <div className="flex h-[240px] items-center justify-center text-sm text-fg-muted">
          Loading…
        </div>
      ) : bars.length === 0 ? (
        <EmptyState
          title="No activity yet"
          message="Entity-type breakdown will chart here once records, schemas, or datasets change in this range."
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
