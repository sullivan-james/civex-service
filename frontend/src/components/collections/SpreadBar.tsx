import type { CollectionStorageReport } from '../../api/store'
import { formatSize } from '../../utils/storage'
import { STATE_TONE, type VolumeState } from '../../utils/volumes'
import { SegmentBar } from '../ui'

/** A collection's data as a bar split by drive, each part in its drive's
 * status colour (the shared `SegmentBar`). */
export function SpreadBar({
  report,
  className,
}: {
  report: CollectionStorageReport
  className?: string
}) {
  return (
    <SegmentBar
      label="Where the files are"
      className={className}
      parts={report.volumes.map((v) => ({
        key: v.volume,
        label: `${v.volume}: ${formatSize(v.bytes)}`,
        value: v.bytes,
        tone: STATE_TONE[v.state as VolumeState] ?? 'neutral',
      }))}
    />
  )
}
