import type {
  JobStatusPoint,
  PluginFailurePoint,
  AuditEventPoint,
} from '../../api/analytics'
import type { TimeSeriesPoint } from './TimeSeriesChart'
import type { BarBreakdownDatum } from './BarBreakdown'

export interface JobSuccessRateSummary {
  /** One point per bucket, `rate` as a 0-100 integer percentage of
   * completed among settled (completed + failed) runs. */
  series: TimeSeriesPoint[]
  totalCompleted: number
  totalFailed: number
}

/** Pivots per-bucket-per-status job counts into a per-bucket success-rate
 * series -- pending/running jobs aren't "settled" yet, so they're counted
 * toward neither a bucket's rate nor the totals. */
export function jobSuccessRateSeries(
  items: JobStatusPoint[],
): JobSuccessRateSummary {
  const byBucket = new Map<string, { completed: number; failed: number }>()
  let totalCompleted = 0
  let totalFailed = 0
  for (const item of items) {
    const entry = byBucket.get(item.bucket) ?? { completed: 0, failed: 0 }
    if (item.status === 'completed') {
      entry.completed += item.count
      totalCompleted += item.count
    } else if (item.status === 'failed') {
      entry.failed += item.count
      totalFailed += item.count
    }
    byBucket.set(item.bucket, entry)
  }
  const series: TimeSeriesPoint[] = [...byBucket.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([bucket, { completed, failed }]) => {
      const settled = completed + failed
      return {
        date: bucket,
        rate: settled === 0 ? 0 : Math.round((completed / settled) * 100),
      }
    })
  return { series, totalCompleted, totalFailed }
}

/** Sums per-bucket-per-plugin failure counts into one total per plugin,
 * most failures first -- the widget cares about "which plugin fails most
 * in this range", not a per-bucket trend. */
export function sumFailuresByPlugin(
  items: PluginFailurePoint[],
): BarBreakdownDatum[] {
  const totals = new Map<string, number>()
  for (const item of items) {
    totals.set(item.plugin, (totals.get(item.plugin) ?? 0) + item.count)
  }
  return [...totals.entries()]
    .sort(([, a], [, b]) => b - a)
    .map(([label, value]) => ({ label, value }))
}

export interface AuditActivitySummary {
  /** One point per bucket, one numeric key per action present anywhere in
   * the range (0 where an action didn't occur in that bucket) -- lets the
   * chart plot create/update/delete as separate series instead of one
   * combined line. */
  series: TimeSeriesPoint[]
  actions: string[]
  total: number
}

/** Pivots per-bucket-per-action audit counts into a per-bucket, per-action
 * series -- the activity-over-time widget's shape, so the breakdown by
 * action survives instead of collapsing into a single count. */
export function auditActivitySeries(
  items: AuditEventPoint[],
): AuditActivitySummary {
  const byBucket = new Map<string, Record<string, number>>()
  const actions = new Set<string>()
  let total = 0
  for (const item of items) {
    const entry = byBucket.get(item.bucket) ?? {}
    entry[item.action] = (entry[item.action] ?? 0) + item.count
    byBucket.set(item.bucket, entry)
    actions.add(item.action)
    total += item.count
  }
  const sortedActions = [...actions].sort()
  const series: TimeSeriesPoint[] = [...byBucket.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([bucket, counts]) => {
      const point: TimeSeriesPoint = { date: bucket }
      for (const action of sortedActions) point[action] = counts[action] ?? 0
      return point
    })
  return { series, actions: sortedActions, total }
}

/** Sums per-bucket-per-entity-type audit counts into one total per entity
 * type, most active first -- the entity-type breakdown widget cares about
 * "what's being changed most in this range", not a per-bucket trend. */
export function sumAuditByEntityType(
  items: AuditEventPoint[],
): BarBreakdownDatum[] {
  const totals = new Map<string, number>()
  for (const item of items) {
    totals.set(
      item.entity_type,
      (totals.get(item.entity_type) ?? 0) + item.count,
    )
  }
  return [...totals.entries()]
    .sort(([, a], [, b]) => b - a)
    .map(([label, value]) => ({ label, value }))
}
