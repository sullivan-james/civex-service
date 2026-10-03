import type { CollectionStorageReport } from '../../api/store'
import { formatSize } from '../../utils/storage'

/** A collection's data as a bar split by volume: the volume holding most in the
 * accent colour, the rest in another, so a split is visible at a glance. */
export function SpreadBar({
  report,
  className = 'h-2',
}: {
  report: CollectionStorageReport
  className?: string
}) {
  return (
    <div
      role="img"
      aria-label={report.volumes
        .map((v) => `${v.volume}: ${formatSize(v.bytes)}`)
        .join(', ')}
      className={`flex overflow-hidden rounded-full bg-canvas-inset ${className}`}
    >
      {report.volumes.map((v, i) => (
        <div
          key={v.volume}
          className={i === 0 ? 'bg-accent' : 'bg-attention'}
          style={{ width: `${(v.bytes / Math.max(report.bytes, 1)) * 100}%` }}
        />
      ))}
    </div>
  )
}
