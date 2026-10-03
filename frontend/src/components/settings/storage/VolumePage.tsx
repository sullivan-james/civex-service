import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { useCollections } from '../../../hooks/useCollections'
import {
  useAllCollectionStorage,
  usePlacements,
  useVolumes,
} from '../../../hooks/useStore'
import { useTransfers } from '../../../hooks/useTransfers'
import { errorMessage } from '../../../lib/errors'
import { formatSize } from '../../../utils/storage'
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  Skeleton,
  Table,
  Tbody,
  Td,
  Th,
  Thead,
  Tr,
} from '../../ui'
import { ArrowLeft, Network } from '../../ui/icons'
import { NewTransferModal, type TransferPreset } from './NewTransferModal'
import { StatusDot } from './StatusDot'
import { TransferCard } from './TransferCard'
import { useVolumeActions } from './useVolumeActions'
import { NEEDS_ATTENTION, STATE_LABEL } from './volumeState'
import { VolumeSpace } from './VolumeSpace'

const STORAGE = '/settings/storage'

/** One volume, with everything about it in one place: its state and what to do
 * about a problem, its space, its part in the write queue, which collections
 * are on it, what on it is unused, and the moves that involve it. */
export default function VolumePage() {
  const { name = '' } = useParams()
  const navigate = useNavigate()
  const { data: volumes, isLoading, error } = useVolumes()
  const { data: placements = [] } = usePlacements()
  const { data: spreads = [] } = useAllCollectionStorage()
  const { data: collections = [] } = useCollections()
  const { data: transfers = [] } = useTransfers()
  const actions = useVolumeActions(() => navigate(STORAGE))
  const [moving, setMoving] = useState<TransferPreset | null>(null)

  const vol = volumes?.find((v) => v.name === name)

  // Collections on this volume: those with files here, and those whose home it
  // is (which may have none yet).
  const rows = useMemo(() => {
    const names = new Map(collections.map((c) => [c.id, c.name]))
    const byId = new Map<
      string,
      {
        id: string
        files: number
        bytes: number
        shared: number
        home: boolean
      }
    >()
    for (const r of spreads) {
      const share = r.volumes.find((v) => v.volume === name)
      if (share)
        byId.set(r.collection_id, {
          id: r.collection_id,
          files: share.files,
          bytes: share.bytes,
          shared: share.shared_files,
          home: false,
        })
    }
    for (const p of placements.filter((p) => p.volume === name)) {
      const row = byId.get(p.collection_id)
      if (row) row.home = true
      else
        byId.set(p.collection_id, {
          id: p.collection_id,
          files: 0,
          bytes: 0,
          shared: 0,
          home: true,
        })
    }
    return [...byId.values()]
      .map((r) => ({ ...r, name: names.get(r.id) ?? 'A deleted collection' }))
      .sort((a, b) => b.bytes - a.bytes || a.name.localeCompare(b.name))
  }, [collections, spreads, placements, name])

  if (isLoading)
    return (
      <div className="space-y-3" aria-hidden="true">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  if (error) return <ErrorState message={errorMessage(error)} />
  if (!vol)
    return (
      <div className="space-y-4">
        <BackLink />
        <EmptyState
          title={`No volume called “${name}”`}
          message="It may have been removed."
        />
      </div>
    )

  const attention = NEEDS_ATTENTION.includes(vol.state)
  const total = vol.civex_used_bytes ?? rows.reduce((n, r) => n + r.bytes, 0)
  const queueIndex = actions.queueNames.indexOf(vol.name)
  const mine = transfers.filter(
    (t) =>
      t.spec.sources.includes(vol.name) || t.spec.targets.includes(vol.name),
  )
  const homed = placements.filter((p) => p.volume === vol.name).length

  return (
    <div className="space-y-6">
      <BackLink />

      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-lg font-semibold text-fg">{vol.name}</h2>
          <span className="inline-flex items-center gap-2 text-sm text-fg">
            <StatusDot state={vol.state} />
            {STATE_LABEL[vol.state]}
          </span>
          {vol.network && (
            <Badge variant="accent">
              <Network size={11} className="mr-1" aria-hidden="true" />
              Network
            </Badge>
          )}
        </div>
        <p className="break-all font-mono text-xs text-fg-muted">{vol.path}</p>
        {attention && (
          <div
            role="alert"
            className="space-y-1 rounded-md border border-attention-muted bg-attention-subtle px-4 py-3 text-sm"
          >
            <p
              className={
                vol.state === 'wrong_drive' ? 'text-danger' : 'text-attention'
              }
            >
              {vol.reason}
            </p>
            {vol.fix && <p className="text-fg-muted">{vol.fix}</p>}
            {vol.state === 'wrong_drive' && (
              <button
                type="button"
                onClick={() => actions.adopt(vol)}
                className="cursor-pointer text-accent hover:underline"
              >
                This is the right drive…
              </button>
            )}
            <p className="text-fg-muted">
              The list below comes from Civex&apos;s records, so it is complete
              even while the drive is away; its files can&apos;t be opened until
              it is back.
            </p>
          </div>
        )}
      </header>

      <section aria-label="Summary" className="grid gap-6 md:grid-cols-3">
        <div>
          <h3 className="mb-2 text-sm font-semibold text-fg">Space</h3>
          <VolumeSpace vol={vol} />
        </div>
        <div>
          <h3 className="mb-2 text-sm font-semibold text-fg">Used for</h3>
          <p className="text-sm text-fg-muted">
            {queueIndex >= 0
              ? `New files: number ${queueIndex + 1} in the write queue.`
              : 'Not in the write queue, so only collections that have it as their home put new files here.'}
          </p>
          <p className="mt-1 text-sm text-fg-muted">
            {homed > 0
              ? `Home of ${homed} ${homed === 1 ? 'collection' : 'collections'}.`
              : 'Not the home of any collection.'}
          </p>
        </div>
        <div className="flex flex-wrap content-start gap-2">
          <Button size="sm" onClick={() => actions.edit(vol)}>
            Edit…
          </Button>
          <Button size="sm" onClick={() => actions.toggleQueue(vol.name)}>
            {queueIndex >= 0 ? 'Remove from write queue' : 'Add to write queue'}
          </Button>
          {!attention && (
            <Button size="sm" onClick={() => setMoving({ source: vol.name })}>
              Move everything off…
            </Button>
          )}
          <Button
            size="sm"
            variant="danger"
            onClick={() => actions.remove(vol)}
          >
            Remove…
          </Button>
        </div>
      </section>

      <section aria-labelledby="on-volume" className="space-y-3">
        <h3 id="on-volume" className="text-base font-semibold text-fg">
          What is on this volume
        </h3>
        {rows.length === 0 &&
        vol.unused_files === 0 &&
        vol.history_files === 0 ? (
          <EmptyState title="Nothing is stored here yet" />
        ) : (
          <Table>
            <Thead>
              <Tr>
                <Th>Collection</Th>
                <Th>Files</Th>
                <Th>Size</Th>
                <Th>Share of this volume</Th>
                <Th>
                  <span className="sr-only">Actions</span>
                </Th>
              </Tr>
            </Thead>
            <Tbody>
              {rows.map((r) => (
                <Tr key={r.id}>
                  <Td>
                    <Link
                      to={`/collections/${r.id}`}
                      className="font-medium text-accent hover:underline"
                    >
                      {r.name}
                    </Link>
                    {r.home && (
                      <span className="ml-2 text-xs text-fg-muted">home</span>
                    )}
                    {r.shared > 0 && (
                      <p className="text-xs text-fg-subtle">
                        {r.shared} {r.shared === 1 ? 'file is' : 'files are'}{' '}
                        also used by other collections
                      </p>
                    )}
                  </Td>
                  <Td>{r.files.toLocaleString()}</Td>
                  <Td>{formatSize(r.bytes)}</Td>
                  <Td className="w-48">
                    <ShareBar bytes={r.bytes} total={total} />
                  </Td>
                  <Td className="text-right">
                    {r.files > 0 && (
                      <button
                        type="button"
                        onClick={() => setMoving({ collectionId: r.id })}
                        className="cursor-pointer text-sm text-accent hover:underline"
                      >
                        Move…
                      </button>
                    )}
                  </Td>
                </Tr>
              ))}
              {vol.history_files > 0 && (
                <Tr>
                  <Td>
                    <span className="text-fg">Workflow run history</span>
                    <p className="text-xs text-fg-subtle">
                      Kept because a workflow run took these files as input. No
                      collection uses them now.
                    </p>
                  </Td>
                  <Td>{vol.history_files.toLocaleString()}</Td>
                  <Td>{formatSize(vol.history_bytes)}</Td>
                  <Td>
                    <ShareBar bytes={vol.history_bytes} total={total} muted />
                  </Td>
                  <Td />
                </Tr>
              )}
              {vol.unused_files > 0 && (
                <Tr>
                  <Td>
                    <span className="text-fg">Unused</span>
                    <p className="text-xs text-fg-subtle">
                      Nothing uses these files. Cleaning up reclaims the space.
                    </p>
                  </Td>
                  <Td>{vol.unused_files.toLocaleString()}</Td>
                  <Td>{formatSize(vol.unused_bytes)}</Td>
                  <Td>
                    <ShareBar bytes={vol.unused_bytes} total={total} muted />
                  </Td>
                  <Td className="text-right">
                    <Link
                      to={`${STORAGE}?tab=tasks`}
                      className="text-sm text-accent hover:underline"
                    >
                      Clean up
                    </Link>
                  </Td>
                </Tr>
              )}
            </Tbody>
          </Table>
        )}
        <p className="text-xs text-fg-subtle">
          A file used by several collections is counted in each, so these rows
          can add up to more than the volume holds.
        </p>
      </section>

      {mine.length > 0 && (
        <section aria-labelledby="its-moves" className="space-y-3">
          <h3 id="its-moves" className="text-base font-semibold text-fg">
            Moves involving this volume
          </h3>
          <ul className="space-y-3">
            {mine.map((t) => (
              <TransferCard key={t.id} t={t} />
            ))}
          </ul>
        </section>
      )}

      {actions.dialogs}
      {moving && (
        <NewTransferModal preset={moving} onClose={() => setMoving(null)} />
      )}
    </div>
  )
}

function BackLink() {
  return (
    <Link
      to={STORAGE}
      className="inline-flex items-center gap-1 text-sm text-accent hover:underline"
    >
      <ArrowLeft size={14} aria-hidden="true" /> Storage
    </Link>
  )
}

function ShareBar({
  bytes,
  total,
  muted = false,
}: {
  bytes: number
  total: number
  muted?: boolean
}) {
  const pct = total > 0 ? Math.min(100, Math.round((bytes / total) * 100)) : 0
  return (
    <div
      role="img"
      aria-label={`${pct}% of this volume`}
      className="h-1.5 overflow-hidden rounded-full bg-canvas-inset"
    >
      <div
        className={muted ? 'h-full bg-fg-subtle' : 'h-full bg-accent'}
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}
