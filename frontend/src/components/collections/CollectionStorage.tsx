import { AlertTriangle } from '../ui/icons'
import { Button } from '../ui'
import { usePlacements, useVolumes } from '../../hooks/useStore'
import { STATE_LABEL } from '../settings/storage/volumeState'
import { CollectionFileLocations } from './CollectionFileLocations'

/** Whether a collection has any storage choice to make: a second volume
 * exists, or a home is already set. A single-volume project never needs the
 * Storage tab. */
export function useHasStorageChoice(collectionId: string): boolean {
  const { data: volumes = [] } = useVolumes()
  const { data: placements = [] } = usePlacements()
  return (
    volumes.length >= 2 ||
    placements.some((p) => p.collection_id === collectionId)
  )
}

/** Where this collection's files are and where its new files go: a report, not
 * a control. Changing a home volume or moving files is done in Settings >
 * Storage, in one place, so the two can never disagree; this links straight
 * there, to this collection. */
export function CollectionStorage({ collectionId }: { collectionId: string }) {
  const { data: volumes = [] } = useVolumes()
  const { data: placements = [] } = usePlacements()

  const current = placements.find((p) => p.collection_id === collectionId)
  const home = volumes.find((v) => v.name === current?.volume)

  return (
    <div className="max-w-xl space-y-4">
      <CollectionFileLocations
        collectionId={collectionId}
        home={current?.volume}
      />

      <section aria-label="Where new files go" className="space-y-1 text-sm">
        <p className="font-medium text-fg">Where new files go</p>
        {current ? (
          <p className="text-fg-muted">
            To <strong className="text-fg">{current.volume}</strong>
            {home && ` (${STATE_LABEL[home.state].toLowerCase()})`}.{' '}
            {current.on_unavailable === 'fail'
              ? "If it can't take a file, the upload is refused."
              : "If it can't take a file, they go wherever there's room."}
          </p>
        ) : (
          <p className="text-fg-muted">
            Wherever there&apos;s room (the general write order). This
            collection has no home volume.
          </p>
        )}
        {home && home.state !== 'online' && (
          <p className="flex items-start gap-1.5 text-xs text-attention">
            <AlertTriangle size={13} className="mt-0.5 shrink-0" />
            <span>
              {home.reason || `The home volume is ${home.state}.`}
              {home.fix && ` ${home.fix}`}
            </span>
          </p>
        )}
        <Button
          size="sm"
          variant="link"
          to={`/settings/storage?tab=collections&focus=${collectionId}`}
        >
          Change where new files go
        </Button>
      </section>
    </div>
  )
}
