import { formatEstimate } from './dbFormat'
import { formatSize } from './storage'

/** How far a transfer has got, as one line beside its bar: how many of how
 * many, how many bytes of how many, how fast, how long left. Moves, downloads
 * and sync all say it this way. Parts that aren't known are left out. */
export function describeAmounts({
  done,
  total,
  unit,
  bytesDone,
  bytesTotal,
  rate,
  eta,
}: {
  done: number
  total?: number | null
  /** What is counted, as it reads after the numbers: "files", "changes". */
  unit?: string
  bytesDone?: number
  bytesTotal?: number
  rate?: number
  eta?: number | null
}): string {
  const of =
    total != null && total > 0
      ? `${done.toLocaleString()} of ${total.toLocaleString()}`
      : done.toLocaleString()
  const shown = [unit ? `${of} ${unit}` : of]
  if (bytesDone)
    shown.push(
      bytesTotal
        ? `${formatSize(bytesDone)} of ${formatSize(bytesTotal)}`
        : formatSize(bytesDone),
    )
  if (rate && rate > 0) shown.push(`${formatSize(rate)}/s`)
  if (eta != null && eta > 0)
    shown.push(`${formatEstimate(Math.round(eta))} left`)
  return shown.join(' · ')
}
