import {
  Bar,
  BarChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  chartAxisLineProps,
  chartAxisTickStyle,
  chartGridProps,
} from './chartTheme'
import { ChartTooltip } from './ChartTooltip'

export interface DurationHistogramBin {
  /** Display label for the bucket, e.g. "0-1s". */
  label: string
  count: number
}

export interface DurationHistogramPercentile {
  label: string
  /** Must match a bin's `label` — recharts places category ReferenceLines
   * by matching the axis's dataKey value. */
  binLabel: string
}

export interface DurationHistogramProps {
  bins: DurationHistogramBin[]
  percentiles?: DurationHistogramPercentile[]
  height?: number
  formatCount?: (count: number) => string
  barColor?: string
}

/** Distribution chart for job/step durations, bucketed by the caller into
 * bins. Percentile markers (p50/p95/...) are drawn as vertical reference
 * lines against a bin label rather than computed here — bucketing strategy
 * and percentile math are widget concerns. */
export function DurationHistogram({
  bins,
  percentiles = [],
  height = 240,
  formatCount,
  barColor = 'var(--color-chart-1)',
}: DurationHistogramProps) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={bins} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid {...chartGridProps} />
        <XAxis
          dataKey="label"
          tick={chartAxisTickStyle}
          tickLine={false}
          axisLine={chartAxisLineProps}
        />
        <YAxis
          tickFormatter={formatCount}
          tick={chartAxisTickStyle}
          tickLine={false}
          axisLine={false}
          width={48}
        />
        <Tooltip
          content={<ChartTooltip formatValue={formatCount} />}
          cursor={{ fill: 'var(--color-canvas-inset)' }}
        />
        <Bar
          dataKey="count"
          name="Count"
          fill={barColor}
          radius={[4, 4, 0, 0]}
        />
        {percentiles.map((p) => (
          <ReferenceLine
            key={p.label}
            x={p.binLabel}
            stroke="var(--color-fg-subtle)"
            strokeDasharray="4 4"
            label={{
              value: p.label,
              position: 'top',
              fill: 'var(--color-fg-muted)',
              fontSize: 12,
            }}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  )
}
