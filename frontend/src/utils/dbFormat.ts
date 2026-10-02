/** Human-readable sizes and durations for the database settings. */

export function formatSize(bytes: number | null | undefined): string {
  if (bytes == null) return 'unknown size'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let n = bytes
  let i = 0
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024
    i++
  }
  return `${i === 0 ? n : n.toFixed(1)} ${units[i]}`
}

export function formatEstimate(seconds: number): string {
  if (seconds < 90) return `about ${Math.max(seconds, 5)} seconds`
  return `about ${Math.round(seconds / 60)} minutes`
}

/** "12 seconds" / "3.4 minutes", for a finished move. */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return ''
  if (seconds < 90) return `${Math.round(seconds)} seconds`
  return `${(seconds / 60).toFixed(1)} minutes`
}
