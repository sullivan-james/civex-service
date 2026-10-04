import type { VolumeStats } from '../../../api/store'
import { formatSize } from '../../../utils/storage'

/** How full a volume's disk is, and how much of it Civex uses. */
export function VolumeSpace({ vol }: { vol: VolumeStats }) {
  if (
    !vol.available ||
    vol.disk_total_bytes == null ||
    vol.disk_free_bytes == null
  )
    return <span className="text-fg-subtle">—</span>
  const used = Math.round(
    ((vol.disk_total_bytes - vol.disk_free_bytes) / vol.disk_total_bytes) * 100,
  )
  return (
    <div className="w-44">
      <div
        role="img"
        aria-label={`${used}% of the disk is used`}
        className="h-1.5 overflow-hidden rounded-full bg-canvas-inset"
      >
        <div
          className={`h-full ${vol.warning ? 'bg-attention' : 'bg-accent'}`}
          style={{ width: `${used}%` }}
        />
      </div>
      <p className="mt-1 text-xs text-fg-muted">
        {formatSize(vol.disk_free_bytes)} free of{' '}
        {formatSize(vol.disk_total_bytes)}
      </p>
      <p className="text-xs text-fg-subtle">
        Civex uses {formatSize(vol.civex_used_bytes)}
        {vol.allocated_gb != null ? ` · limit ${vol.allocated_gb} GB` : ''}
      </p>
    </div>
  )
}
