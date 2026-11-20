import type { RecordSummary } from '../../api/records'
import { BarBreakdown } from '../analytics/BarBreakdown'
import { TimeSeriesChart } from '../analytics/TimeSeriesChart'
import { Button, Field, Select } from '../ui'
import type { FilterTreeWire } from '../../utils/filterTree'
import { formatSummaryValue } from '../../utils/summary'
import {
  buildSummaryChart,
  chartMeasures,
  measureAxisLabel,
  noChartReason,
  type ChartAside,
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
}: {
  summary: RecordSummary
  /** The measure on the value axis (null: the first that is a number). */
  measureKey: string | null
  /** Offer a choice of measure (none: the chart is fixed, as on the
   * Analytics page). */
  onMeasure?: (key: string) => void
  /** List a group's records (none: bars and points are not links). */
  onDrill?: (where: FilterTreeWire) => void
}) {
  const reason = noChartReason(summary)
  if (reason) return <p className="text-sm text-fg-muted">{reason}</p>
  const chart = buildSummaryChart(summary, measureKey)
  if (!chart) return null
  const measures = chartMeasures(summary.measure_columns)
  const valueLabel = measureAxisLabel(chart.measure)
  const drill = (index: number, seriesKey: string) => {
    const s = chart.series.findIndex((x) => x.key === seriesKey)
    const where = chart.wheres[index]?.[s]
    if (where && onDrill) onDrill(where)
  }
  const sideways = chart.form === 'bars' && chart.points.length > UPRIGHT_UP_TO
  const height = sideways
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
        ) : chart.form === 'time' ? (
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
            contiguous={chart.form === 'histogram'}
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
