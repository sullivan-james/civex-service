import { useVolumes } from '../../../hooks/useStore'
import { errorMessage } from '../../../lib/errors'
import { ErrorState, EmptyState } from '../../ui'
import { StatTile } from '../StatTile'
import { formatBytes } from '../format'
import { WidgetCard } from '../WidgetCard'

/** Storage usage per volume, from `VolumeStatsResponse` -- a snapshot, not
 * governed by the shared date-range/dataset/schema filter bar since volume
 * usage isn't scoped to any of those dimensions. Full volume management
 * (add/edit/remove, write-queue order) lives in Settings > Storage; this widget only
 * summarizes. */
export function StorageUsageWidget() {
  const { data: volumes, isLoading, error } = useVolumes()

  return (
    <WidgetCard
      title="Storage usage"
      description="Used space by volume"
      viewRunsTo="/settings/storage"
      viewRunsLabel="Manage volumes"
    >
      {error ? (
        <ErrorState message={errorMessage(error)} />
      ) : isLoading ? (
        <div className="flex h-[80px] items-center justify-center text-sm text-fg-muted">
          Loading…
        </div>
      ) : !volumes || volumes.length === 0 ? (
        <EmptyState
          title="No volumes configured"
          message="Add a storage volume in Settings to see usage here."
        />
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {volumes.map((vol) => (
            <StatTile
              key={vol.name}
              label={vol.warning ? `${vol.name} (low space)` : vol.name}
              value={
                vol.civex_used_bytes == null
                  ? '—'
                  : formatBytes(vol.civex_used_bytes)
              }
            />
          ))}
        </div>
      )}
    </WidgetCard>
  )
}
