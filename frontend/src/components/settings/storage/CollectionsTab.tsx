import { useMemo, useState } from 'react'
import { Link } from 'react-router'
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
  Badge,
  Button,
  Checkbox,
  EmptyState,
  ErrorState,
  Input,
  Select,
  Skeleton,
  Table,
  Tbody,
  Td,
  Th,
  Thead,
  Tr,
} from '../../ui'
import { X } from '../../ui/icons'
import { errorMessage } from '../../../lib/errors'
import { STATE_LABEL } from './volumeState'
import { SpreadBar } from '../../collections/SpreadBar'
import { gatherPlan } from '../../../utils/collectionStorage'
import { formatSize } from '../../../utils/storage'
import { NewTransferModal } from './NewTransferModal'

const NONE = ''

function VolumeOptions({ volumes }: { volumes: VolumeStats[] }) {
  return (
    <>
      <option value={NONE}>General write queue</option>
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

/** One collection's home, changed in place and saved as soon as it changes. */
function CollectionRow({
  collection,
  placement,
  volumes,
  spread,
  highlight,
  selected,
  onSelect,
}: {
  collection: Collection
  placement: Placement | undefined
  volumes: VolumeStats[]
  spread: CollectionStorageReport | undefined
  /** A volume being looked at; its share is picked out in the row. */
  highlight: string | null
  selected: boolean
  onSelect: (on: boolean) => void
}) {
  const setPlacement = useSetPlacement()
  const clearPlacement = useClearPlacement()
  const pending = setPlacement.isPending || clearPlacement.isPending
  const error = setPlacement.error ?? clearPlacement.error
  const home = volumes.find((v) => v.name === placement?.volume)
  const gather = spread ? gatherPlan(spread, placement?.volume) : null
  const [gathering, setGathering] = useState(false)

  function changeHome(volume: string) {
    if (volume === NONE) clearPlacement.mutate(collection.id)
    else
      setPlacement.mutate({
        collectionId: collection.id,
        volume,
        onUnavailable: placement?.on_unavailable ?? 'spill',
      })
  }

  function changePolicy(onUnavailable: PlacementPolicy) {
    if (placement)
      setPlacement.mutate({
        collectionId: collection.id,
        volume: placement.volume,
        onUnavailable,
      })
  }

  return (
    <Tr>
      <Td className="w-10">
        <Checkbox
          aria-label={`Select ${collection.name}`}
          checked={selected}
          onChange={(e) => onSelect(e.target.checked)}
        />
      </Td>
      <Td>
        <Link
          to={`/collections/${collection.id}`}
          className="font-medium text-accent hover:underline"
        >
          {collection.name}
        </Link>
        <span className="ml-2 text-xs text-fg-subtle">
          {collection.record_count.toLocaleString()}{' '}
          {collection.record_count === 1 ? 'record' : 'records'}
        </span>
      </Td>
      <Td className="min-w-48">
        {spread && spread.files > 0 ? (
          <div className="space-y-1">
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
            </p>
            {gather && (
              <button
                type="button"
                onClick={() => setGathering(true)}
                className="cursor-pointer text-xs text-accent hover:underline"
              >
                Gather {gather.elsewhere}{' '}
                {gather.elsewhere === 1 ? 'file' : 'files'} onto {gather.target}
                …
              </button>
            )}
            {gathering && gather && (
              <NewTransferModal
                preset={{ collectionId: collection.id, target: gather.target }}
                onClose={() => setGathering(false)}
              />
            )}
          </div>
        ) : (
          <span className="text-xs text-fg-subtle">No files</span>
        )}
      </Td>
      <Td>
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
      </Td>
      <Td>
        {placement ? (
          <Select
            size="sm"
            aria-label={`If the home volume of ${collection.name} can't take a file`}
            value={placement.on_unavailable}
            disabled={pending}
            onChange={(e) => changePolicy(e.target.value as PlacementPolicy)}
          >
            <option value="spill">Use the write queue</option>
            <option value="fail">Refuse the upload</option>
          </Select>
        ) : (
          <span className="text-fg-subtle">—</span>
        )}
      </Td>
      <Td className="whitespace-nowrap">
        {home && home.state !== 'online' ? (
          <Badge variant="danger">
            Home {STATE_LABEL[home.state].toLowerCase()}
          </Badge>
        ) : placement ? (
          <span className="text-fg-muted">Has a home</span>
        ) : (
          <span className="text-fg-subtle">Write queue</span>
        )}
      </Td>
    </Tr>
  )
}

/** Every collection and where its new files go. This is where a volume is
 * assigned to a collection, one at a time or for several at once. */
export function CollectionsTab({
  volumeFilter,
  onClearVolumeFilter,
  onGoToVolumes,
}: {
  volumeFilter: string | null
  onClearVolumeFilter: () => void
  onGoToVolumes: () => void
}) {
  const { data: collections, isLoading, error } = useCollections()
  const { data: placements = [] } = usePlacements()
  const { data: volumes = [] } = useVolumes()
  const { data: spreads = [] } = useAllCollectionStorage()
  const bulk = useBulkPlacement()
  const [query, setQuery] = useState('')
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
      <p className="max-w-prose text-sm text-fg-muted">
        Choose which volume receives each collection&apos;s <em>new</em> files.
        This only decides where new files are written: a file whose content is
        already stored, on any volume, is reused where it is and never copied
        again.
      </p>

      {volumes.length < 2 && placements.length === 0 && (
        <div className="flex items-center justify-between gap-4 rounded-md border border-border bg-canvas-subtle px-4 py-3 text-sm text-fg-muted">
          <span>
            You only have one volume, so every collection uses it. Add another
            to give a collection its own home.
          </span>
          <Button size="sm" onClick={onGoToVolumes}>
            Go to volumes
          </Button>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <Input
          aria-label="Filter collections"
          placeholder="Filter collections"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-64"
        />
        {volumeFilter && (
          <button
            type="button"
            onClick={onClearVolumeFilter}
            className="inline-flex cursor-pointer items-center gap-1 rounded-full border border-accent-muted bg-accent-subtle px-2 py-1 text-xs font-medium text-accent"
          >
            On {volumeFilter}
            <X size={12} aria-label="Clear volume filter" />
          </button>
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

      {collections.length === 0 ? (
        <EmptyState
          title="No collections yet"
          message="Create a collection first, then choose where its files go."
        />
      ) : shown.length === 0 ? (
        <EmptyState title="No collections match" />
      ) : (
        <Table>
          <Thead>
            <Tr>
              <Th className="w-10">
                <Checkbox
                  aria-label="Select all shown collections"
                  checked={allShownSelected}
                  onChange={(e) =>
                    setSelected(
                      e.target.checked
                        ? new Set(shown.map((c) => c.id))
                        : new Set(),
                    )
                  }
                />
              </Th>
              <Th>Collection</Th>
              <Th>Files are on</Th>
              <Th>Home volume</Th>
              <Th>If the home can&apos;t take a file</Th>
              <Th>Status</Th>
            </Tr>
          </Thead>
          <Tbody>
            {shown.map((c) => (
              <CollectionRow
                key={c.id}
                collection={c}
                placement={byId.get(c.id)}
                volumes={volumes}
                spread={spreadById.get(c.id)}
                highlight={volumeFilter}
                selected={selected.has(c.id)}
                onSelect={(on) => toggle(c.id, on)}
              />
            ))}
          </Tbody>
        </Table>
      )}
    </div>
  )
}
