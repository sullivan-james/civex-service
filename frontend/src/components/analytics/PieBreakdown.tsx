import {
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
} from 'recharts'
import { chartLegendProps, seriesColor } from './chartTheme'
import { ChartTooltip } from './ChartTooltip'

export interface PieBreakdownProps {
  /** One slice each: what it is and how big. */
  data: { label: string; value: number }[]
  height?: number
  formatValue?: (value: number) => string
  /** A slice was clicked: its index in `data`. */
  onSliceClick?: (index: number) => void
  animate?: boolean
}

/** Shares of a whole: a slice per category, coloured from the shared chart
 * palette in turn, named in a legend. For counts and totals only (parts that
 * add up); the caller decides when that is so. */
export function PieBreakdown({
  data,
  height = 240,
  formatValue,
  onSliceClick,
  animate = true,
}: PieBreakdownProps) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <PieChart>
        <Pie
          data={data}
          dataKey="value"
          nameKey="label"
          innerRadius="45%"
          outerRadius="80%"
          paddingAngle={1}
          isAnimationActive={animate}
          cursor={onSliceClick ? 'pointer' : undefined}
          onClick={
            onSliceClick
              ? (_: unknown, index: number) => onSliceClick(index)
              : undefined
          }
        >
          {data.map((d, i) => (
            <Cell key={d.label} fill={seriesColor(i)} />
          ))}
        </Pie>
        <Tooltip content={<ChartTooltip formatValue={formatValue} />} />
        <Legend {...chartLegendProps} />
      </PieChart>
    </ResponsiveContainer>
  )
}
