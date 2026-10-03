import { useState } from 'react'
import { StatusDot } from '../settings/storage/StatusDot'
import { NewTransferModal } from '../settings/storage/NewTransferModal'
import { STATE_LABEL } from '../settings/storage/volumeState'
import { useCollectionStorage } from '../../hooks/useStore'
import { Button } from '../ui'
import { formatSize } from '../../utils/storage'

/** Where this collection's files are, volume by volume, and (when they are
 * split) a way to gather them. Read from the catalog, so it is cheap. */
export function CollectionFileLocations({
  collectionId,
  home,
}: {
  collectionId: string
  /** The collection's home volume, if it has one. */
  home?: string
}) {
  const { data } = useCollectionStorage(collectionId)
  const [gathering, setGathering] = useState(false)
  if (!data || data.files === 0) return null

  const split = data.volumes.length > 1
  const largest = data.volumes[0]
  // Gather onto the home if there is one, else where most of it already is.
  const target = home ?? largest?.volume
  const elsewhere = data.volumes.filter((v) => v.volume !== target)
  const notThere = elsewhere.reduce((n, v) => n + v.files, 0)

  return (
    <div className="space-y-2" data-testid="file-locations">
      <p className="text-sm font-medium text-fg">Where the files are</p>
      <p className="text-sm text-fg-muted">
        {data.files} {data.files === 1 ? 'file' : 'files'} (
        {formatSize(data.bytes)}){' '}
        {split ? 'on ' + data.volumes.length + ' volumes' : 'on one volume'}.
      </p>

      <div
        role="img"
        aria-label={data.volumes
          .map((v) => `${v.volume}: ${formatSize(v.bytes)}`)
          .join(', ')}
        className="flex h-2 overflow-hidden rounded-full bg-canvas-inset"
      >
        {data.volumes.map((v, i) => (
          <div
            key={v.volume}
            className={i === 0 ? 'bg-accent' : 'bg-attention'}
            style={{ width: `${(v.bytes / Math.max(data.bytes, 1)) * 100}%` }}
          />
        ))}
      </div>

      <ul className="space-y-1 text-sm">
        {data.volumes.map((v) => (
          <li key={v.volume} className="flex flex-wrap items-center gap-x-2">
            <StatusDot state={v.state} />
            <span className="font-medium text-fg">{v.volume}</span>
            <span className="text-fg-muted">
              {v.files} {v.files === 1 ? 'file' : 'files'} ·{' '}
              {formatSize(v.bytes)}
            </span>
            {v.shared_files > 0 && (
              <span className="text-xs text-fg-subtle">
                {v.shared_files} also used by other collections
              </span>
            )}
            {!v.available && (
              <span className="text-xs text-attention">
                {STATE_LABEL[v.state]}: these files can&apos;t be opened right
                now
              </span>
            )}
          </li>
        ))}
      </ul>

      {data.unlocated_files > 0 && (
        <p className="text-xs text-attention">
          {data.unlocated_files} files aren&apos;t in the storage catalog; a
          storage scan will find them.
        </p>
      )}

      {split && target && notThere > 0 && (
        <Button size="sm" onClick={() => setGathering(true)}>
          Gather onto {target}…
        </Button>
      )}
      {gathering && target && (
        <NewTransferModal
          preset={{ collectionId, target }}
          onClose={() => setGathering(false)}
        />
      )}
    </div>
  )
}
