import { useEffect, useMemo, useRef, useState } from 'react'
import { withRange } from '../../../hooks/useRangeSelect'
import type { Collection } from '../../../api/collections'
import type {
  CollectionStorageReport,
  Placement,
  PlacementPolicy,
  VolumeStats,
} from '../../../api/store'
import { useCollections } from '../../../hooks/useCollections'
import {
  useAllCollectionStorage,
  useBulkPlacement,
  useClearPlacement,
  usePlacements,
  useSetPlacement,
  useVolumes,
} from '../../../hooks/useStore'
import {
  Button,
  DataTable,
  ErrorState,
  InfoTip,
  Input,
  Select,
  Skeleton,
} from '../../ui'
import { X } from '../../ui/icons'
import { errorMessage } from '../../../lib/errors'
import { STATE_LABEL } from '../../../utils/volumes'
import { VolumeStatus } from '../../files/Where'
import { SpreadBar } from '../../collections/SpreadBar'
import { gatherPlan } from '../../../utils/collectionStorage'
import { formatSize } from '../../../utils/storage'
import { NewTransferModal } from './NewTransferModal'
import { ComputerFilesCell, ComputerFilesDefault } from './ComputerFiles'
import { useFollowsServer } from '../../../hooks/useRemote'

const NONE = ''

function VolumeOptions({ volumes }: { volumes: VolumeStats[] }) {
  return (
    <>
      <option value={NONE}>General write order</option>
      {volumes.map((v) => (
        <option key={v.name} value={v.name}>
          {v.name}
          {v.state !== 'online'
            ? ` (${STATE_LABEL[v.state].toLowerCase()})`
            : ''}
        </option>
      ))}
    </>
  )
}

/** A collection's home, changed in place and saved as soon as it changes. */
function useHome(collection: Collection, placement: Placement | undefined) {
  const setPlacement = useSetPlacement()
  const clearPlacement = useClearPlacement()
  return {
    pending: setPlacement.isPending || clearPlacement.isPending,
    error: setPlacement.error ?? clearPlacement.error,
    changeHome(volume: string) {
      if (volume === NONE) clearPlacement.mutate(collection.id)
      else
        setPlacement.mutate({
          collectionId: collection.id,
          volume,
          onUnavailable: placement?.on_unavailable ?? 'spill',
        })
    },
    changePolicy(onUnavailable: PlacementPolicy) {
      if (placement)
        setPlacement.mutate({
          collectionId: collection.id,
          volume: placement.volume,
          onUnavailable,
        })
    },
  }
}

function FilesCell({
  collection,
  placement,
  spread,
  highlight,
}: {
  collection: Collection
  placement: Placement | undefined
  spread: CollectionStorageReport | undefined
  /** A volume being looked at; its share is picked out in the row. */
  highlight: string | null
}) {
  const gather = spread ? gatherPlan(spread, placement?.volume) : null
  const [gathering, setGathering] = useState(false)
  if (!spread || spread.files === 0)
    return <span className="text-fg-subtle">No files</span>
  return (
    <div className="min-w-48 space-y-1">
      <SpreadBar report={spread} className="h-1.5" />
      <p className="text-xs text-fg-muted">
        {spread.volumes.map((v, i) => (
          <span key={v.volume}>
            {i > 0 && ' · '}
            <span
              className={
                v.volume === highlight ? 'font-medium text-fg' : undefined
              }
            >
              {v.volume} {formatSize(v.bytes)}
            </span>
          </span>
        ))}
        {spread.unlocated_files > 0 && (
          <span
            className={
              spread.unlocated_place === 'server' ? undefined : 'text-attention'
            }
          >
            {spread.volumes.length > 0 && ' · '}
            {spread.unlocated_files.toLocaleString()}{' '}
            {spread.unlocated_place === 'server'
              ? 'not on this computer'
              : 'missing'}
          </span>
        )}
      </p>
      {gather && (
        <Button size="sm" variant="link" onClick={() => setGathering(true)}>
          Gather {gather.elsewhere} {gather.elsewhere === 1 ? 'file' : 'files'}{' '}
          onto {gather.target}…
        </Button>
      )}
      {gathering && gather && (
        <NewTransferModal
          preset={{ collectionId: collection.id, target: gather.target }}
          onClose={() => setGathering(false)}
        />
      )}
    </div>
  )
}

function HomeCell({
  collection,
  placement,
  volumes,
}: {
  collection: Collection
  placement: Placement | undefined
  volumes: VolumeStats[]
}) {
  const { pending, error, changeHome } = useHome(collection, placement)
  return (
    <>
      <Select
        size="sm"
        aria-label={`Home volume for ${collection.name}`}
        value={placement?.volume ?? NONE}
        disabled={pending}
        onChange={(e) => changeHome(e.target.value)}
      >
        <VolumeOptions volumes={volumes} />
      </Select>
      {error != null && (
        <p role="alert" className="mt-1 text-xs text-danger">
          {errorMessage(error)}
        </p>
      )}
    </>
  )
}

function PolicyCell({
  collection,
  placement,
}: {
  collection: Collection
  placement: Placement | undefined
}) {
  const { pending, changePolicy } = useHome(collection, placement)
  if (!placement) return <span className="text-fg-subtle">—</span>
  return (
    <Select
      size="sm"
      aria-label={`If the home volume of ${collection.name} can't take a file`}
      value={placement.on_unavailable}
      disabled={pending}
      onChange={(e) => changePolicy(e.target.value as PlacementPolicy)}
    >
      <option value="spill">Use the write order</option>
      <option value="fail">Refuse the upload</option>
    </Select>
  )
}

/** Every collection and where its new files go. This is where a volume is
 * assigned to a collection, one at a time or for several at once. */
export function CollectionsTab({
  focusId,
  volumeFilter,
  onClearVolumeFilter,
  onGoToVolumes,
}: {
  /** A collection to land on (from a link on its own page): the list opens
   * filtered to it, and one click on the filter shows them all. */
  focusId?: string | null
  volumeFilter: string | null
  onClearVolumeFilter: () => void
  onGoToVolumes: () => void
}) {
  const { data: collections, isLoading, error } = useCollections()
  const { data: placements = [] } = usePlacements()
  const { data: volumes = [] } = useVolumes()
  const { data: spreads = [] } = useAllCollectionStorage()
  const bulk = useBulkPlacement()
  const followsServer = useFollowsServer()
  const [query, setQuery] = useState('')
  const focused = useRef(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [bulkVolume, setBulkVolume] = useState(NONE)

  const spreadById = useMemo(
    () => new Map(spreads.map((r) => [r.collection_id, r])),
    [spreads],
  )
  const byId = useMemo(
    () => new Map(placements.map((p) => [p.collection_id, p])),
    [placements],
  )

  const focusName = focusId
    ? collections?.find((c) => c.id === focusId)?.name
    : undefined
  useEffect(() => {
    if (focusName && !focused.current) {
      focused.current = true
      setQuery(focusName)
    }
  }, [focusName])

  if (isLoading)
    return (
      <div className="space-y-3" aria-hidden="true">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  if (error || !collections)
    return (
      <ErrorState
        message={error ? errorMessage(error) : 'Failed to load collections'}
      />
    )

  const shown = collections
    .filter((c) => c.name.toLowerCase().includes(query.trim().toLowerCase()))
    // On a volume: it has files there, or it is the collection's home.
    .filter(
      (c) =>
        !volumeFilter ||
        byId.get(c.id)?.volume === volumeFilter ||
        spreadById.get(c.id)?.volumes.some((v) => v.volume === volumeFilter),
    )
    .sort((a, b) => a.name.localeCompare(b.name))
  const allShownSelected =
    shown.length > 0 && shown.every((c) => selected.has(c.id))

  function toggle(id: string, on: boolean) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (on) next.add(id)
      else next.delete(id)
      return next
    })
  }

  return (
    <div className="space-y-4">
      {volumes.length < 2 && placements.length === 0 && (
        <div className="flex items-center justify-between gap-4 rounded-md border border-border bg-canvas-subtle px-4 py-3 text-sm text-fg-muted">
          <span>One volume: every collection uses it.</span>
          <Button size="sm" onClick={onGoToVolumes}>
            Add a volume
          </Button>
        </div>
      )}

      {followsServer && <ComputerFilesDefault />}

      <div className="flex flex-wrap items-center gap-3">
        <Input
          aria-label="Filter collections"
          placeholder="Filter collections"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-64"
        />
        <InfoTip>
          Choose which volume receives each collection&apos;s new files. A file
          whose content is already stored, on any volume, is reused where it is
          and never copied again.
        </InfoTip>
        {volumeFilter && (
          <Button size="sm" variant="link" onClick={onClearVolumeFilter}>
            On {volumeFilter}
            <X size={12} aria-label="Clear volume filter" />
          </Button>
        )}
      </div>

      {selected.size > 0 && (
        <div
          role="region"
          aria-label="Bulk actions"
          className="flex flex-wrap items-center gap-3 rounded-md border border-accent-muted bg-accent-subtle px-4 py-2 text-sm"
        >
          <span className="font-medium text-fg">{selected.size} selected</span>
          <Select
            size="sm"
            aria-label="Home volume for the selected collections"
            value={bulkVolume}
            onChange={(e) => setBulkVolume(e.target.value)}
            className="w-56"
          >
            <VolumeOptions volumes={volumes} />
          </Select>
          <Button
            size="sm"
            variant="primary"
            disabled={bulk.isPending}
            onClick={() =>
              bulk.mutate(
                { collectionIds: [...selected], volume: bulkVolume },
                { onSuccess: () => setSelected(new Set()) },
              )
            }
          >
            Apply
          </Button>
          <Button size="sm" onClick={() => setSelected(new Set())}>
            Clear selection
          </Button>
          {bulk.isError && (
            <span role="alert" className="text-xs text-danger">
              {errorMessage(bulk.error)}
            </span>
          )}
        </div>
      )}

      <DataTable
        layout="auto"
        columns={[
          {
            key: 'collection',
            header: 'Collection',
            render: (c: Collection) => (
              <>
                <span className="font-medium">{c.name}</span>
                <span className="ml-2 text-xs text-fg-subtle">
                  {c.record_count.toLocaleString()}{' '}
                  {c.record_count === 1 ? 'record' : 'records'}
                </span>
              </>
            ),
          },
          {
            key: 'files',
            header: 'Files are on',
            render: (c) => (
              <FilesCell
                collection={c}
                placement={byId.get(c.id)}
                spread={spreadById.get(c.id)}
                highlight={volumeFilter}
              />
            ),
          },
          ...(followsServer
            ? [
                {
                  key: 'computer',
                  header: (
                    <span className="inline-flex items-center gap-1">
                      On this computer
                      <InfoTip>
                        Keep a collection&apos;s files here (downloaded in the
                        background), or fetch each when it is opened or
                        exported. Freeing space removes this computer&apos;s
                        copies of files the server holds.
                      </InfoTip>
                    </span>
                  ),
                  render: (c: Collection) => (
                    <ComputerFilesCell collectionId={c.id} />
                  ),
                },
              ]
            : []),
          {
            key: 'home',
            header: 'Home volume',
            render: (c) => (
              <HomeCell
                collection={c}
                placement={byId.get(c.id)}
                volumes={volumes}
              />
            ),
          },
          {
            key: 'policy',
            header: (
              <span className="inline-flex items-center gap-1">
                If home is full
                <InfoTip>
                  What happens when the home volume can&apos;t take a file:
                  write it by the general write order, or refuse the upload.
                </InfoTip>
              </span>
            ),
            render: (c) => (
              <PolicyCell collection={c} placement={byId.get(c.id)} />
            ),
          },
          {
            key: 'status',
            header: 'Status',
            className: 'whitespace-nowrap',
            render: (c) => {
              const placement = byId.get(c.id)
              const home = volumes.find((v) => v.name === placement?.volume)
              return home && home.state !== 'online' ? (
                <span className="inline-flex items-center gap-1">
                  Home
                  <VolumeStatus
                    state={home.state}
                    reason={home.reason}
                    fix={home.fix}
                  />
                </span>
              ) : placement ? (
                <span className="text-fg-muted">Has a home</span>
              ) : (
                <span className="text-fg-subtle">Write order</span>
              )
            },
          },
        ]}
        rows={shown}
        getRowId={(c) => c.id}
        rowHref={(c) => `/collections/${c.id}`}
        selection={{
          selected,
          onToggle: (id) => toggle(id, !selected.has(id)),
          onSetMany: (ids, on) =>
            setSelected((prev) => withRange(prev, ids, on)),
          onToggleAll: () =>
            setSelected(
              allShownSelected ? new Set() : new Set(shown.map((c) => c.id)),
            ),
          allLabel: 'Select all shown collections',
          rowLabel: (id) =>
            `Select ${collections.find((c) => c.id === id)?.name ?? id}`,
        }}
        emptyTitle={
          collections.length === 0
            ? 'No collections yet'
            : 'No collections match'
        }
      />
    </div>
  )
}
