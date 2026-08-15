import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
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

export interface TimeSeriesSeries {
  /** Key into each data point that holds this series' value. */
  key: string
  label: string
  /** CSS colour value; defaults to the shared chart palette by index. */
  color?: string
}

export interface TimeSeriesPoint {
  [key: string]: number | string
}

export interface TimeSeriesChartProps {
  data: TimeSeriesPoint[]
  series: TimeSeriesSeries[]
  /** Key into each data point that holds the x-axis value. Defaults to `'date'`. */
  xKey?: string
  variant?: 'line' | 'area'
  height?: number
  formatValue?: (value: number) => string
  formatXAxis?: (value: string) => string
}

/** Line/area chart over a date range, plotting one or more series. Data is
 * plain fixture-shaped objects — this component has no knowledge of what a
 * "job" or "record" is, so widgets adapt their own data into it. */
export function TimeSeriesChart({
  data,
  series,
  xKey = 'date',
  variant = 'line',
  height = 240,
  formatValue,
  formatXAxis,
}: TimeSeriesChartProps) {
  const ChartComponent = variant === 'area' ? AreaChart : LineChart

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ChartComponent
        data={data}
        margin={{ top: 8, right: 8, left: 0, bottom: 0 }}
      >
        <CartesianGrid {...chartGridProps} />
        <XAxis
          dataKey={xKey}
          tickFormatter={formatXAxis}
          tick={chartAxisTickStyle}
          tickLine={false}
          axisLine={chartAxisLineProps}
          minTickGap={24}
        />
        <YAxis
          tickFormatter={formatValue}
          tick={chartAxisTickStyle}
          tickLine={false}
          axisLine={false}
          width={48}
        />
        <Tooltip
          content={<ChartTooltip formatValue={formatValue} />}
          cursor={{ stroke: 'var(--color-border)' }}
        />
        {series.map((s, index) => {
          const color = seriesColor(index, s.color)
          if (variant === 'area') {
            return (
              <Area
                key={s.key}
                type="monotone"
                dataKey={s.key}
                name={s.label}
                stroke={color}
                fill={color}
                fillOpacity={0.15}
                strokeWidth={2}
              />
            )
          }
          return (
            <Line
              key={s.key}
              type="monotone"
              dataKey={s.key}
              name={s.label}
              stroke={color}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4 }}
            />
          )
        })}
      </ChartComponent>
    </ResponsiveContainer>
  )
}
