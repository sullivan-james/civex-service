/**
 * A summary as a chart: which form (bars for categories, a histogram for
 * number ranges, a line over time for date periods, from the first grouping's
 * kind), which values sit on the axis and which are told apart beside it (no
 * value, a date less precise than the period), and the filter condition behind
 * every bar or point, so clicking one lists exactly the records a table row
 * would. Pure: the chart component only draws what this returns.
 */

import type {
  RecordSummary,
  SummaryGroupColumn,
  SummaryMeasureColumn,
  SummaryRow,
} from '../api/records'
import type { FilterTreeWire } from './filterTree'
import { formatSummaryValue } from './summary'

export type ChartForm = 'bars' | 'histogram' | 'time'

/** The most series (values of the second grouping) a chart draws; the table
 * has the rest. Five is as many as the chart palette tells apart. */
export const MAX_SERIES = 5
/** Past this many periods or ranges, empty ones are not filled in. */
const MAX_FILLED = 1000
/** Measures for which a period or range with no records is 0, not unknown. */
const ZERO_WHEN_EMPTY = new Set(['count', 'filled', 'distinct', 'sum'])
/** Measures whose values add up across series, so their bars can stack. */
const ADDITIVE = new Set(['count', 'filled', 'sum'])

/** A date period on an axis, from its first day (`YYYY-MM-DD`) and how the
 * dates were grouped. The one place a chart writes a date: point this at the
 * app's date formatter when there is one. */
export function periodLabel(lower: string, bucket: string | null): string {
  if (bucket === 'year') return lower.slice(0, 4)
  if (bucket === 'month') return lower.slice(0, 7)
  return lower.slice(0, 10)
}

/** The measures a chart can put on its axis: those that are numbers. */
export function chartMeasures(
  columns: SummaryMeasureColumn[],
): SummaryMeasureColumn[] {
  return columns.filter(
    (c) =>
      c.measure === 'count' ||
      c.measure === 'filled' ||
      c.measure === 'distinct' ||
      c.type === 'integer' ||
      c.type === 'float',
  )
}

export function chartForm(column: SummaryGroupColumn): ChartForm {
  if ((column.type === 'date' || column.type === 'datetime') && column.bucket)
    return 'time'
  if ((column.type === 'integer' || column.type === 'float') && column.bin)
    return 'histogram'
  return 'bars'
}

/** The axis title for a measure: its label and unit. */
export function measureAxisLabel(m: SummaryMeasureColumn): string {
  return m.unit ? `${m.label} (${m.unit})` : m.label
}

export interface ChartSeries {
  /** The key of its values in each point (`s0`, `s1`, ...). */
  key: string
  label: string
}

export interface ChartPoint {
  /** What the axis shows. */
  axis: string
  /** What the tooltip says the point is. */
  label: string
  [series: string]: string | number | null
}

/** A group not on the axis: no value, or a date less precise than the period. */
export interface ChartAside {
  label: string
  value: unknown
  where: FilterTreeWire | null
}

export interface SummaryChart {
  form: ChartForm
  measure: SummaryMeasureColumn
  series: ChartSeries[]
  points: ChartPoint[]
  /** `wheres[point][series]`: what clicking that bar or point lists (null:
   * an empty period, or a group a filter can't say). */
  wheres: (FilterTreeWire | null)[][]
  stacked: boolean
  noValue: ChartAside[]
  partial: ChartAside[]
  /** Values of the second grouping left out (more than MAX_SERIES). */
  hiddenSeries: number
}

/** Why there is no chart, in plain words; null when there is one. */
export function noChartReason(summary: RecordSummary): string | null {
  const groups = summary.group_columns.length
  if (groups === 0) return 'Add a grouping to draw a chart.'
  if (groups > 2)
    return 'A chart shows one or two groupings; the table has all three.'
  if (chartMeasures(summary.measure_columns).length === 0)
    return 'Nothing shown is a number to chart. Add a count or an average.'
  return null
}

const seriesKey = (i: number) => `s${i}`
const keyOf = (v: unknown) => JSON.stringify(v ?? null)
/** A range's start as a key, free of float noise (0.30000000000000004). */
const rangeKey = (n: number) => String(Number(n.toPrecision(12)))

/** Build the chart for `summary`, with `measureKey` on the axis (else the
 * first measure that is a number). Null when there is none to draw. */
export function buildSummaryChart(
  summary: RecordSummary,
  measureKey: string | null,
): SummaryChart | null {
  if (noChartReason(summary)) return null
  const measures = chartMeasures(summary.measure_columns)
  const measure = measures.find((m) => m.key === measureKey) ?? measures[0]
  const mi = summary.measure_columns.indexOf(measure)
  const first = summary.group_columns[0]
  const form = chartForm(first)
  const two = summary.group_columns.length === 2
  const num = (row: SummaryRow): number | null => {
    const v = row.values[mi]
    return typeof v === 'number' ? v : null
  }

  // Groups beside the axis.
  const noValue: ChartAside[] = []
  const partial: ChartAside[] = []
  const plotted: SummaryRow[] = []
  for (const row of summary.rows) {
    const g = row.groups[0]
    const label = two ? `${g.label} · ${row.groups[1].label}` : g.label
    const aside = { label, value: row.values[mi], where: row.where }
    if (g.value === null) noValue.push(aside)
    else if (form === 'time' && g.precision) partial.push(aside)
    else plotted.push(row)
  }

  // Series: one, or the second grouping's values, largest first.
  let series: ChartSeries[] = [{ key: seriesKey(0), label: measure.label }]
  const seriesOf = new Map<string, number>()
  let hiddenSeries = 0
  if (two) {
    const totals = new Map<string, { label: string; total: number }>()
    for (const row of plotted) {
      const g = row.groups[1]
      const k = keyOf(g.value)
      const t = totals.get(k) ?? { label: g.label, total: 0 }
      t.total += Math.abs(num(row) ?? 0)
      totals.set(k, t)
    }
    const ordered = [...totals.entries()].sort(
      (a, b) => b[1].total - a[1].total,
    )
    hiddenSeries = Math.max(0, ordered.length - MAX_SERIES)
    series = ordered.slice(0, MAX_SERIES).map(([k, t], i) => {
      seriesOf.set(k, i)
      return { key: seriesKey(i), label: t.label }
    })
  } else seriesOf.set('', 0)

  // Points along the axis, in the server's order (by group value).
  const points: ChartPoint[] = []
  const wheres: (FilterTreeWire | null)[][] = []
  const at = new Map<string, number>()
  const pointAt = (k: string, axis: string, label: string) => {
    let i = at.get(k)
    if (i === undefined) {
      i = points.length
      at.set(k, i)
      const p: ChartPoint = { axis, label }
      for (const s of series) p[s.key] = null
      points.push(p)
      wheres.push(series.map(() => null))
    }
    return i
  }
  const axisKey = (row: SummaryRow) => {
    const g = row.groups[0]
    if (form === 'time') return String(g.lower ?? g.value)
    if (form === 'histogram') return rangeKey(Number(g.lower ?? g.value))
    return keyOf(g.value)
  }
  const axisText = (row: SummaryRow) => {
    const g = row.groups[0]
    if (form === 'time')
      return periodLabel(String(g.lower ?? g.value), first.bucket)
    if (form === 'histogram') return formatSummaryValue(g.lower ?? g.value)
    return g.label
  }

  // Empty periods and ranges between the first and the last: drawn as 0 (or
  // a gap) so the axis is even.
  const keys = filledKeys(form, first, plotted)
  for (const k of keys) {
    const text =
      form === 'time'
        ? periodLabel(k, first.bucket)
        : formatSummaryValue(Number(k))
    const label =
      form === 'histogram'
        ? `${text} to under ${formatSummaryValue(Number(k) + (first.bin ?? 0))}`
        : text
    const i = pointAt(k, text, label)
    if (ZERO_WHEN_EMPTY.has(measure.measure))
      for (const s of series) points[i][s.key] = 0
  }
  for (const row of plotted) {
    const s = seriesOf.get(two ? keyOf(row.groups[1].value) : '')
    if (s === undefined) continue
    const i = pointAt(
      axisKey(row),
      axisText(row),
      form === 'time' ? axisText(row) : row.groups[0].label,
    )
    points[i][seriesKey(s)] = num(row)
    wheres[i][s] = row.where
  }

  return {
    form,
    measure,
    series,
    points,
    wheres,
    stacked: two && ADDITIVE.has(measure.measure),
    noValue,
    partial,
    hiddenSeries,
  }
}

/** Every period or range from the first plotted to the last, in order (none
 * for categories, or when there would be too many). */
function filledKeys(
  form: ChartForm,
  column: SummaryGroupColumn,
  rows: SummaryRow[],
): string[] {
  if (rows.length < 2 || form === 'bars') return []
  const lowers = rows.map((r) => r.groups[0].lower ?? r.groups[0].value)
  if (form === 'histogram') {
    const bin = column.bin ?? 0
    const nums = lowers.map(Number).filter((n) => Number.isFinite(n))
    if (!bin || nums.length < 2) return []
    const lo = Math.min(...nums)
    const steps = Math.round((Math.max(...nums) - lo) / bin)
    if (steps > MAX_FILLED) return []
    return Array.from({ length: steps + 1 }, (_, i) => rangeKey(lo + i * bin))
  }
  const dates = lowers.map(String).sort()
  const out: string[] = []
  let d = new Date(`${dates[0].slice(0, 10)}T00:00:00Z`)
  const last = dates[dates.length - 1].slice(0, 10)
  if (Number.isNaN(d.getTime())) return []
  while (out.length <= MAX_FILLED) {
    const iso = d.toISOString().slice(0, 10)
    if (iso > last) return out
    out.push(iso)
    d = nextPeriod(d, column.bucket)
  }
  return []
}

function nextPeriod(d: Date, bucket: string | null): Date {
  const n = new Date(d)
  if (bucket === 'year') n.setUTCFullYear(n.getUTCFullYear() + 1)
  else if (bucket === 'month') n.setUTCMonth(n.getUTCMonth() + 1)
  else if (bucket === 'week') n.setUTCDate(n.getUTCDate() + 7)
  else n.setUTCDate(n.getUTCDate() + 1)
  return n
}
