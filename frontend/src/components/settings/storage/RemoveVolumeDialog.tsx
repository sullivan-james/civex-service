import type { VolumeStats } from '../../../api/store'
import { ConfirmDialog } from '../../ui'
import { useRemoveVolume } from '../../../hooks/useStore'
import { errorMessage } from '../../../lib/errors'
import { formatSize } from '../../../utils/storage'

/** Removing a volume from Civex, with what it will and won't do spelled out.
 * Nothing is ever deleted from the drive. */
export function RemoveVolumeDialog({
  vol,
  homedCount,
  onClose,
}: {
  vol: VolumeStats
  /** Collections that use this volume as their home. */
  homedCount: number
  onClose: () => void
}) {
  const removeVolume = useRemoveVolume()
  // An unreachable volume's contents can't be read, so it may well hold files.
  const used = vol.civex_used_bytes
  const holdsFiles = used === null || used > 0
  const needsForce = holdsFiles || homedCount > 0

  return (
    <ConfirmDialog
      title={`Remove volume “${vol.name}”?`}
      confirmLabel="Remove volume"
      variant="danger"
      // Losing track of files is the one consequential outcome, so it takes a
      // typed confirmation; an unused volume is just one click.
      typedConfirmationValue={holdsFiles ? vol.name : undefined}
      isPending={removeVolume.isPending}
      warning={
        removeVolume.isError ? errorMessage(removeVolume.error) : undefined
      }
      body={
        <div className="space-y-3 text-sm">
          <p>
            This removes the volume from Civex.{' '}
            <strong>Nothing is deleted from the drive.</strong>
          </p>
          <ul className="list-disc space-y-1 pl-5 text-fg-muted">
            {used === null ? (
              <li>
                Civex can&apos;t see what is on it right now, so it may hold
                files. Records that use them will show those files as
                unavailable until the volume is added back with the same folder.
              </li>
            ) : (
              used > 0 && (
                <li>
                  It holds <strong>{formatSize(used)}</strong> of Civex files.
                  Records that use them will show those files as unavailable
                  until the volume is added back with the same folder.
                </li>
              )
            )}
            {homedCount > 0 && (
              <li>
                {homedCount}{' '}
                {homedCount === 1 ? 'collection uses' : 'collections use'} it as{' '}
                {homedCount === 1 ? 'its' : 'their'} home and will go back to
                the general write queue.
              </li>
            )}
            {vol.in_queue && <li>It leaves the write queue.</li>}
            {!holdsFiles && homedCount === 0 && !vol.in_queue && (
              <li>Nothing uses it right now.</li>
            )}
          </ul>
        </div>
      }
      onConfirm={() =>
        removeVolume.mutate(
          { name: vol.name, force: needsForce },
          { onSuccess: onClose },
        )
      }
      onClose={onClose}
    />
  )
}
