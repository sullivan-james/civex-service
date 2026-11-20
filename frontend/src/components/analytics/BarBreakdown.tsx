import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  chartAxisLineProps,
  chartAxisTickStyle,
  chartGridProps,
  chartLegendProps,
  chartValueAxisLabel,
  seriesColor,
} from './chartTheme'
import { ChartTooltip } from './ChartTooltip'

export interface BarBreakdownDatum {
  label: string
  value: number
  /** CSS colour value for this bar; defaults to the shared chart palette. */
  color?: string
}

/** A category with a value per series (`series`), keyed by series key. */
export interface BarBreakdownRow {
  label: string
  [series: string]: string | number | null
}

export interface BarBreakdownSeries {
  /** Key into each row that holds this series' value. */
  key: string
  label: string
  color?: string
}

export interface BarBreakdownProps {
  data: BarBreakdownDatum[] | BarBreakdownRow[]
  /** 'vertical' draws bars as horizontal rows (categories on the y-axis) —
   * better for long or numerous category labels. Defaults to 'horizontal'
   * (upright columns). */
  layout?: 'horizontal' | 'vertical'
  height?: number
  formatValue?: (value: number) => string
  seriesLabel?: string
  /** Several values per category: one bar each (side by side, or `stacked`),
   * coloured by series in order. Without it each datum's `value` is one bar
   * and the bars take the palette in turn. */
  series?: BarBreakdownSeries[]
  stacked?: boolean
  /** Ranges that follow on from each other (a histogram): bars nearly touch. */
  contiguous?: boolean
  /** Key of the row's text for the axis (default `label`); the tooltip names
   * the row by `tooltipKey` when given (a range's full wording). */
  categoryKey?: string
  tooltipKey?: string
  /** Title of the value axis (the measure, with its unit). */
  valueLabel?: string
  /** A bar was clicked: its category's index and series key. */
  onBarClick?: (index: number, seriesKey: string) => void
}

/** Categorical bar chart for counts-by-X breakdowns (schema, plugin,
 * action, a summary's groups ...), one series or several. Each datum is an
 * independent category — the caller decides what the categories mean. */
export function BarBreakdown({
  data,
  layout = 'horizontal',
  height = 240,
  formatValue,
  seriesLabel = 'Count',
  series,
  stacked = false,
  contiguous = false,
  categoryKey = 'label',
  tooltipKey,
  valueLabel,
  onBarClick,
}: BarBreakdownProps) {
  const isVertical = layout === 'vertical'
  const end: [number, number, number, number] = isVertical
    ? [0, 4, 4, 0]
    : [4, 4, 0, 0]
  const click = (key: string) =>
    onBarClick
      ? (_: unknown, index: number) => onBarClick(index, key)
      : undefined
  const many = !!series && series.length > 1

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart
        data={data as Array<Record<string, unknown>>}
        layout={layout}
        margin={{ top: 8, right: 8, left: valueLabel ? 12 : 0, bottom: 0 }}
        barCategoryGap={contiguous ? 1 : '10%'}
        barGap={2}
      >
        <CartesianGrid
          {...chartGridProps}
          horizontal={!isVertical}
          vertical={isVertical}
        />
        {isVertical ? (
          <>
            <XAxis
              type="number"
              tickFormatter={formatValue}
              tick={chartAxisTickStyle}
              tickLine={false}
              axisLine={false}
              label={chartValueAxisLabel(valueLabel, 'x')}
            />
            <YAxis
              type="category"
              dataKey={categoryKey}
              tick={chartAxisTickStyle}
              tickLine={false}
              axisLine={chartAxisLineProps}
              width={96}
            />
          </>
        ) : (
          <>
            <XAxis
              dataKey={categoryKey}
              tick={chartAxisTickStyle}
              tickLine={false}
              axisLine={chartAxisLineProps}
              minTickGap={8}
            />
            <YAxis
              tickFormatter={formatValue}
              tick={chartAxisTickStyle}
              tickLine={false}
              axisLine={false}
              width={56}
              label={chartValueAxisLabel(valueLabel, 'y')}
            />
          </>
        )}
        <Tooltip
          content={
            <ChartTooltip formatValue={formatValue} labelKey={tooltipKey} />
          }
          cursor={{ fill: 'var(--color-canvas-inset)' }}
        />
        {many && <Legend {...chartLegendProps} />}
        {series ? (
          series.map((s, index) => (
            <Bar
              key={s.key}
              dataKey={s.key}
              name={s.label}
              fill={seriesColor(index, s.color)}
              stackId={stacked ? 'stack' : undefined}
              // Only the top of a stack is rounded; a 2px surface line parts
              // the segments.
              radius={!stacked || index === series.length - 1 ? end : 0}
              stroke={stacked ? 'var(--color-canvas)' : undefined}
              strokeWidth={stacked ? 2 : 0}
              cursor={onBarClick ? 'pointer' : undefined}
              onClick={click(s.key)}
            />
          ))
        ) : (
          <Bar
            dataKey="value"
            name={seriesLabel}
            radius={end}
            cursor={onBarClick ? 'pointer' : undefined}
            onClick={click('value')}
          >
            {(data as BarBreakdownDatum[]).map((entry, index) => (
              <Cell key={entry.label} fill={seriesColor(index, entry.color)} />
            ))}
          </Bar>
        )}
      </BarChart>
    </ResponsiveContainer>
  )
}
