import { ArrowDown, ArrowUp, Minus } from '../ui/icons'

export interface StatTileProps {
  label: string
  value: string | number
  /** Change vs. a prior period, in the same units the caller already
   * formats `deltaLabel` around (percentage points, absolute count, ...). */
  delta?: number
  /** e.g. "vs previous 7 days". Shown next to the delta. */
  deltaLabel?: string
  /** Which direction of `delta` should read as "good" (green). Defaults to
   * 'up' — set to 'down' for metrics like error count or latency, where a
   * decrease is the improvement. */
  goodDirection?: 'up' | 'down'
  formatDelta?: (delta: number) => string
}

const trendClasses = {
  positive: 'text-success',
  negative: 'text-danger',
  flat: 'text-fg-muted',
}

/** Single-number KPI tile with an optional trend delta. Renders as a plain
 * card — widgets that need a grid of these compose their own layout. */
export function StatTile({
  label,
  value,
  delta,
  deltaLabel,
  goodDirection = 'up',
  formatDelta = (d) => `${d > 0 ? '+' : ''}${d}%`,
}: StatTileProps) {
  const trend =
    delta == null || delta === 0 ? 'flat' : delta > 0 ? 'up' : 'down'
  const sentiment =
    trend === 'flat'
      ? 'flat'
      : trend === goodDirection
        ? 'positive'
        : 'negative'
  const TrendIcon =
    trend === 'up' ? ArrowUp : trend === 'down' ? ArrowDown : Minus

  return (
    <div className="flex flex-col gap-1 rounded-lg border border-border bg-canvas p-4">
      <span className="text-xs font-medium text-fg-muted">{label}</span>
      <span className="text-2xl font-semibold text-fg">{value}</span>
      {delta != null && (
        <span
          className={`flex items-center gap-1 text-xs font-medium ${trendClasses[sentiment]}`}
        >
          <TrendIcon size={12} />
          {formatDelta(delta)}
          {deltaLabel && (
            <span className="font-normal text-fg-subtle">{deltaLabel}</span>
          )}
        </span>
      )}
    </div>
  )
}
