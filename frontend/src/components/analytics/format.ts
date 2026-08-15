/** Formats a duration given in seconds as a compact human string, e.g. for
 * axis ticks and tooltips on DurationHistogram. */
export function formatDurationSeconds(seconds: number): string {
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)}m`
  return `${(seconds / 3600).toFixed(1)}h`
}

/** Formats a count as a compact number, e.g. 12_400 -> "12.4k", for axis
 * ticks where full-precision numbers would crowd the chart. */
export function formatCompactNumber(value: number): string {
  const abs = Math.abs(value)
  if (abs < 1000) return String(value)
  if (abs < 1_000_000) return `${(value / 1000).toFixed(abs < 10_000 ? 1 : 0)}k`
  return `${(value / 1_000_000).toFixed(1)}M`
}
