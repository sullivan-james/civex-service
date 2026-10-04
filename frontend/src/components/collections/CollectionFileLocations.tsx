import { StatusDot } from '../settings/storage/StatusDot'
import { STATE_LABEL } from '../settings/storage/volumeState'
import { useCollectionStorage, useVolumes } from '../../hooks/useStore'
import { Button } from '../ui'
import { gatherPlan } from '../../utils/collectionStorage'
import { formatSize } from '../../utils/storage'
import { SpreadBar } from './SpreadBar'

/** Where this collection's files are, volume by volume, and (when they are
 * split) a link to gather them in Settings. A report: moving files is done in
 * one place, Settings > Storage. Read from the catalog, so it is cheap. */
export function CollectionFileLocations({
  collectionId,
  home,
}: {
  collectionId: string
  /** The collection's home volume, if it has one. */
  home?: string
}) {
  const { data } = useCollectionStorage(collectionId)
  const { data: volumes = [] } = useVolumes()
  if (!data || data.files === 0) return null

  const split = data.volumes.length > 1
  const plan = gatherPlan(data, home)

  return (
    <div className="space-y-2" data-testid="file-locations">
      <p className="text-sm font-medium text-fg">Where the files are</p>
      <p className="text-sm text-fg-muted">
        {data.files} {data.files === 1 ? 'file' : 'files'} (
        {formatSize(data.bytes)}){' '}
        {split ? 'on ' + data.volumes.length + ' volumes' : 'on one volume'}.
      </p>

      <SpreadBar report={data} />

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
                now.
                {/* Which drive to plug in, from the volume's own status. */}
                {(() => {
                  const fix = volumes.find((x) => x.name === v.volume)?.fix
                  return fix ? ` ${fix}` : ''
                })()}
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

      {plan && (
        <Button
          size="sm"
          to={`/settings/storage?tab=tasks&collection=${collectionId}&to=${encodeURIComponent(plan.target)}`}
        >
          Gather onto {plan.target}…
        </Button>
      )}
    </div>
  )
}
