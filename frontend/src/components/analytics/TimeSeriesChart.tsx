import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
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
  chartLegendProps,
  chartValueAxisLabel,
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
  /** A missing value (null) is a gap in the line, not a zero. */
  [key: string]: number | string | null
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
  /** Title of the value axis (a measure, with its unit). */
  valueLabel?: string
  /** Title the tooltip with this key of the point instead of the x value. */
  tooltipKey?: string
  /** A point was clicked: its index in `data` and its series' key. Each
   * point then has a marker and a hit area larger than it. */
  onPointClick?: (index: number, seriesKey: string) => void
  /** Mark each point (when there are few enough to tell apart). */
  markers?: boolean
}

/** Past this many points, a line has no markers (unless they are clickable). */
const MARKERS_UP_TO = 60

interface DotProps {
  cx?: number
  cy?: number
  index?: number
  value?: unknown
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
  valueLabel,
  tooltipKey,
  onPointClick,
  markers: wantMarkers = false,
}: TimeSeriesChartProps) {
  const ChartComponent = variant === 'area' ? AreaChart : LineChart
  const markers = wantMarkers && data.length <= MARKERS_UP_TO
  // A marker (8px, ringed by the surface) and, when points can be clicked,
  // a larger invisible hit area around it.
  const dot =
    (key: string, color: string) =>
    ({ cx, cy, index, value }: DotProps) => {
      if (cx == null || cy == null || value == null || index == null)
        return <g key={`${key}-${index}`} />
      return (
        <g
          key={`${key}-${index}`}
          style={onPointClick ? { cursor: 'pointer' } : undefined}
          onClick={onPointClick ? () => onPointClick(index, key) : undefined}
        >
          {onPointClick && <circle cx={cx} cy={cy} r={10} fill="transparent" />}
          {markers && (
            <circle
              cx={cx}
              cy={cy}
              r={4}
              fill={color}
              stroke="var(--color-canvas)"
              strokeWidth={2}
            />
          )}
        </g>
      )
    }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ChartComponent
        data={data}
        margin={{ top: 8, right: 8, left: valueLabel ? 12 : 0, bottom: 0 }}
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
          width={valueLabel ? 56 : 48}
          label={chartValueAxisLabel(valueLabel, 'y')}
        />
        <Tooltip
          content={
            <ChartTooltip formatValue={formatValue} labelKey={tooltipKey} />
          }
          cursor={{ stroke: 'var(--color-border)' }}
        />
        {series.length > 1 && <Legend {...chartLegendProps} />}
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
              dot={markers || onPointClick ? dot(s.key, color) : false}
              activeDot={{ r: 5 }}
            />
          )
        })}
      </ChartComponent>
    </ResponsiveContainer>
  )
}
