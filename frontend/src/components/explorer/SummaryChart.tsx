import type { RecordSummary } from '../../api/records'
import { BarBreakdown } from '../analytics/BarBreakdown'
import { PieBreakdown } from '../analytics/PieBreakdown'
import { TimeSeriesChart } from '../analytics/TimeSeriesChart'
import { Button, Field, ListButton, Select } from '../ui'
import type { FilterTreeWire } from '../../utils/filterTree'
import { formatSummaryValue } from '../../utils/summary'
import {
  buildSummaryChart,
  chartMeasures,
  measureAxisLabel,
  noChartReason,
  type ChartAside,
  type SummaryChart as SummaryChartModel,
} from '../../utils/summaryChart'

/** Past this many categories, bars lie on their side so the names fit. */
const UPRIGHT_UP_TO = 10
/** The most groups listed by name beside a chart (no value, partial dates). */
const ASIDE_SHOWN = 6

const formatValue = (n: number) => formatSummaryValue(n)

/** A summary drawn: bars for categories, a histogram for ranges of a number,
 * a line over time for date periods (the first grouping decides), the second
 * grouping as series. Clicking a bar or a point lists its records, as clicking
 * the table's row does. */
export function SummaryChart({
  summary,
  measureKey,
  onMeasure,
  onDrill,
  compact = false,
  lit,
  as,
}: {
  summary: RecordSummary
  /** The measure on the value axis (null: the first that is a number). */
  measureKey: string | null
  /** Offer a choice of measure (none: the chart is fixed, as on the
   * Analytics page). */
  onMeasure?: (key: string) => void
  /** List a group's records (none: bars and points are not links). */
  onDrill?: (where: FilterTreeWire) => void
  /** Draw it small, for a card: one row per bar, each a button. */
  compact?: boolean
  /** Draw it as bars, a line or a pie whatever its grouping would pick
   * (none: a line over time for dates, bars otherwise). */
  as?: 'bars' | 'line' | 'pie' | null
  /** Which bars are chosen (the rest are dimmed); none: nothing is. */
  lit?: ((where: FilterTreeWire | null) => boolean) | null
}) {
  const reason = noChartReason(summary)
  if (reason) return <p className="text-sm text-fg-muted">{reason}</p>
  const chart = buildSummaryChart(summary, measureKey)
  if (!chart) return null
  // In a card, categories are a row per bar (each a button that says
  // whether it is chosen); a line over time and a histogram keep their own
  // form, smaller, so a card looks like the chart it opens as.
  const draw =
    as === 'pie' && chart.series.length > 1
      ? 'bars' // a pie is of one thing
      : (as ?? (chart.form === 'time' ? 'line' : 'bars'))
  if (
    compact &&
    draw === 'bars' &&
    chart.series.length === 1 &&
    chart.form === 'bars'
  )
    return <BarRows chart={chart} onDrill={onDrill} lit={lit ?? null} />
  const measures = chartMeasures(summary.measure_columns)
  const valueLabel = measureAxisLabel(chart.measure)
  const drill = (index: number, seriesKey: string) => {
    const s = chart.series.findIndex((x) => x.key === seriesKey)
    const where = chart.wheres[index]?.[s]
    if (where && onDrill) onDrill(where)
  }
  const sideways = chart.form === 'bars' && chart.points.length > UPRIGHT_UP_TO
  const height = compact
    ? 180
    : sideways
      ? Math.min(Math.max(240, chart.points.length * 24 + 40), 900)
      : 300
  const what = summary.group_columns.map((c) => c.label).join(' and ')

  return (
    <div className="space-y-2">
      {measures.length > 1 && onMeasure && (
        <div className="flex items-center gap-2">
          <span className="text-sm text-fg-muted">Chart</span>
          <Field label="What to chart" hideLabel>
            <Select
              size="sm"
              value={chart.measure.key}
              onChange={(e) => onMeasure(e.target.value)}
            >
              {measures.map((m) => (
                <option key={m.key} value={m.key}>
                  {measureAxisLabel(m)}
                </option>
              ))}
            </Select>
          </Field>
        </div>
      )}
      <figure
        aria-label={`${valueLabel} by ${what}`}
        data-chart-form={chart.form}
        className="m-0"
      >
        {chart.points.length === 0 ? (
          <p className="text-sm text-fg-muted">Nothing to draw on the axis.</p>
        ) : draw === 'pie' ? (
          <PieBreakdown
            data={chart.points.map((p) => ({
              label: p.label,
              value: Number(p[chart.series[0].key] ?? 0),
            }))}
            height={height}
            formatValue={formatValue}
            onSliceClick={
              onDrill ? (i) => drill(i, chart.series[0].key) : undefined
            }
            animate={false}
          />
        ) : draw === 'line' ? (
          <TimeSeriesChart
            data={chart.points}
            series={chart.series}
            xKey="axis"
            tooltipKey="label"
            height={height}
            formatValue={formatValue}
            valueLabel={valueLabel}
            onPointClick={onDrill ? drill : undefined}
            animate={false}
            markers
          />
        ) : (
          <BarBreakdown
            data={chart.points as never}
            series={chart.series}
            stacked={chart.stacked}
            contiguous={chart.form !== 'bars'}
            layout={sideways ? 'vertical' : 'horizontal'}
            categoryKey="axis"
            tooltipKey="label"
            height={height}
            formatValue={formatValue}
            valueLabel={valueLabel}
            onBarClick={onDrill ? drill : undefined}
            animate={false}
          />
        )}
      </figure>
      {chart.hiddenSeries > 0 && (
        <p className="text-xs text-fg-muted">
          The {chart.series.length} largest of{' '}
          {chart.series.length + chart.hiddenSeries}{' '}
          {summary.group_columns[1].label} values are drawn; the table has them
          all.
        </p>
      )}
      <Aside
        title="Not on the axis: no value"
        items={chart.noValue}
        onDrill={onDrill}
      />
      <Aside
        title="Not on the axis: dates less precise than the period"
        items={chart.partial}
        onDrill={onDrill}
      />
    </div>
  )
}

/** How many rows a card shows before the rest wait for it to be opened. */
const ROWS_SHOWN = 12

/** A chart small enough for a card: a row per bar (label, bar, value), the
 * same points, order and conditions as the full chart (`buildSummaryChart`).
 * Each row is a button that says whether it is chosen. */
function BarRows({
  chart,
  onDrill,
  lit,
}: {
  chart: SummaryChartModel
  onDrill?: (where: FilterTreeWire) => void
  lit: ((where: FilterTreeWire | null) => boolean) | null
}) {
  const key = chart.series[0].key
  const rows = [
    ...chart.points.map((p, i) => ({
      label: p.label,
      value: p[key] as number | null,
      where: chart.wheres[i][0],
    })),
    ...[...chart.partial, ...chart.noValue].map((a) => ({
      label: a.label,
      value: typeof a.value === 'number' ? a.value : null,
      where: a.where,
    })),
  ]
  if (rows.length === 0)
    return <p className="text-sm text-fg-muted">Nothing to show</p>
  const top = Math.max(...rows.map((r) => Math.abs(r.value ?? 0)), 0)
  const shown = rows.slice(0, ROWS_SHOWN)
  return (
    <div>
      {shown.map((r, i) => {
        const on = lit ? lit(r.where) : false
        const clickable = !!onDrill && !!r.where
        return (
          <ListButton
            key={`${i}-${r.label}`}
            className={`!min-h-8 rounded !px-1 !py-1 ${lit && !on ? 'opacity-50' : ''}`}
            aria-pressed={clickable ? on : undefined}
            disabled={!clickable}
            onClick={() => r.where && onDrill?.(r.where)}
          >
            <span className="grid grid-cols-[minmax(0,6rem)_1fr_auto] items-center gap-2 text-fg">
              <span className="truncate" title={r.label}>
                {r.label}
              </span>
              <span className="h-3 overflow-hidden rounded-sm bg-canvas-inset">
                <span
                  className="block h-3 rounded-sm bg-accent"
                  style={{
                    width: `${top ? (Math.abs(r.value ?? 0) / top) * 100 : 0}%`,
                  }}
                />
              </span>
              <span className="tabular-nums">
                {formatSummaryValue(r.value)}
              </span>
            </span>
          </ListButton>
        )
      })}
      {rows.length > shown.length && (
        <p className="px-1 pt-1 text-xs text-fg-muted">
          {rows.length - shown.length} more
        </p>
      )}
    </div>
  )
}

/** Groups a chart can't place, said beside it with their values, each a way
 * to list its records. */
function Aside({
  title,
  items,
  onDrill,
}: {
  title: string
  items: ChartAside[]
  onDrill?: (where: FilterTreeWire) => void
}) {
  if (items.length === 0) return null
  const shown = items.slice(0, ASIDE_SHOWN)
  return (
    <div className="flex flex-wrap items-center gap-x-2 text-xs text-fg-muted">
      <span>{title}:</span>
      {shown.map((a) =>
        a.where && onDrill ? (
          <Button
            key={a.label}
            variant="link"
            size="sm"
            onClick={() => onDrill(a.where!)}
          >
            {a.label} ({formatSummaryValue(a.value)})
          </Button>
        ) : (
          <span key={a.label}>
            {a.label} ({formatSummaryValue(a.value)})
          </span>
        ),
      )}
      {items.length > shown.length && (
        <span>and {items.length - shown.length} more in the table</span>
      )}
    </div>
  )
}
