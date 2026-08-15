import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  chartAxisLineProps,
  chartAxisTickStyle,
  chartGridProps,
  seriesColor,
} from './chartTheme'
import { ChartTooltip } from './ChartTooltip'

export interface BarBreakdownDatum {
  label: string
  value: number
  /** CSS colour value for this bar; defaults to the shared chart palette. */
  color?: string
}

export interface BarBreakdownProps {
  data: BarBreakdownDatum[]
  /** 'vertical' draws bars as horizontal rows (categories on the y-axis) —
   * better for long or numerous category labels. Defaults to 'horizontal'
   * (upright columns). */
  layout?: 'horizontal' | 'vertical'
  height?: number
  formatValue?: (value: number) => string
  seriesLabel?: string
}

/** Categorical bar chart for counts-by-X breakdowns (schema, plugin,
 * action, ...). Each datum is an independent label/value pair — the caller
 * decides what the categories mean. */
export function BarBreakdown({
  data,
  layout = 'horizontal',
  height = 240,
  formatValue,
  seriesLabel = 'Count',
}: BarBreakdownProps) {
  const isVertical = layout === 'vertical'

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart
        data={data}
        layout={layout}
        margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
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
            />
            <YAxis
              type="category"
              dataKey="label"
              tick={chartAxisTickStyle}
              tickLine={false}
              axisLine={chartAxisLineProps}
              width={96}
            />
          </>
        ) : (
          <>
            <XAxis
              dataKey="label"
              tick={chartAxisTickStyle}
              tickLine={false}
              axisLine={chartAxisLineProps}
            />
            <YAxis
              tickFormatter={formatValue}
              tick={chartAxisTickStyle}
              tickLine={false}
              axisLine={false}
              width={48}
            />
          </>
        )}
        <Tooltip
          content={<ChartTooltip formatValue={formatValue} />}
          cursor={{ fill: 'var(--color-canvas-inset)' }}
        />
        <Bar
          dataKey="value"
          name={seriesLabel}
          radius={isVertical ? [0, 4, 4, 0] : [4, 4, 0, 0]}
        >
          {data.map((entry, index) => (
            <Cell key={entry.label} fill={seriesColor(index, entry.color)} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
