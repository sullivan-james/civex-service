import type {
  JobStatusPoint,
  PluginFailurePoint,
  RecordCount,
  RecordGrowthPoint,
} from '../../api/analytics'
import type { TimeSeriesPoint, TimeSeriesSeries } from './TimeSeriesChart'
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

export interface RecordGrowthSummary {
  /** One point per bucket, with one numeric key per dataset/schema combo
   * present in that bucket. */
  series: TimeSeriesPoint[]
  /** One chart series per dataset/schema combo seen anywhere in `items`. */
  seriesKeys: TimeSeriesSeries[]
  total: number
}

/** Pivots per-bucket-per-dataset-per-schema growth points into a
 * multi-series time chart -- one line per dataset/schema combo, since the
 * shared filter bar's `dataset`/`schema` filters may leave more than one
 * combo in range. */
export function recordGrowthSeries(
  items: RecordGrowthPoint[],
): RecordGrowthSummary {
  const combos = new Set<string>()
  const byBucket = new Map<string, Record<string, number>>()
  let total = 0
  for (const item of items) {
    const key = `${item.dataset}/${item.schema_name}`
    combos.add(key)
    const entry = byBucket.get(item.bucket) ?? {}
    entry[key] = (entry[key] ?? 0) + item.count
    byBucket.set(item.bucket, entry)
    total += item.count
  }
  const series: TimeSeriesPoint[] = [...byBucket.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([bucket, counts]) => ({ date: bucket, ...counts }))
  const seriesKeys: TimeSeriesSeries[] = [...combos]
    .sort()
    .map((key) => ({ key, label: key }))
  return { series, seriesKeys, total }
}

/** Sums per-dataset-per-schema record counts into one total per schema,
 * most records first -- the widget cares about "which schema has the most
 * records", not the per-dataset split. */
export function sumRecordCountsBySchema(
  items: RecordCount[],
): BarBreakdownDatum[] {
  const totals = new Map<string, number>()
  for (const item of items) {
    totals.set(
      item.schema_name,
      (totals.get(item.schema_name) ?? 0) + item.count,
    )
  }
  return [...totals.entries()]
    .sort(([, a], [, b]) => b - a)
    .map(([label, value]) => ({ label, value }))
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
