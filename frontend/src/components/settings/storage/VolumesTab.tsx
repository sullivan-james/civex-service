import { useState } from 'react'
import type { VolumeStats } from '../../../api/store'
import {
  useAdoptVolume,
  useAllCollectionStorage,
  usePlacements,
  useSetQueue,
  useVolumes,
} from '../../../hooks/useStore'
import {
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Skeleton,
  Table,
  Tbody,
  Th,
  Thead,
  Tr,
} from '../../ui'
import { AlertTriangle, ArrowRight, Plus } from '../../ui/icons'
import { errorMessage } from '../../../lib/errors'
import { formatSize } from '../../../utils/storage'
import { AddVolumeModal } from '../AddVolumeModal'
import { EditVolumeModal } from './EditVolumeModal'
import { RemoveVolumeDialog } from './RemoveVolumeDialog'
import { VolumeRow } from './VolumeRow'
import { NEEDS_ATTENTION } from './volumeState'

/** The volumes Civex keeps files on, one row each. */
export function VolumesTab() {
  const { data: volumes, isLoading, error } = useVolumes()
  const { data: placements = [] } = usePlacements()
  const { data: spreads = [] } = useAllCollectionStorage()
  const setQueue = useSetQueue()
  const adopt = useAdoptVolume()
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<VolumeStats | null>(null)
  const [removing, setRemoving] = useState<VolumeStats | null>(null)
  const [adopting, setAdopting] = useState<VolumeStats | null>(null)

  if (isLoading)
    return (
      <div className="space-y-3" aria-hidden="true">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-40 w-full" />
      </div>
    )
  if (error || !volumes)
    return (
      <ErrorState
        message={error ? errorMessage(error) : 'Failed to load volumes'}
      />
    )

  const queueNames = volumes.filter((v) => v.in_queue).map((v) => v.name)
  const homesOf = (name: string) =>
    placements.filter((p) => p.volume === name).length
  // Collections with files on a volume, or that use it as their home.
  const collectionsOn = (name: string) =>
    new Set([
      ...placements
        .filter((p) => p.volume === name)
        .map((p) => p.collection_id),
      ...spreads
        .filter((r) => r.volumes.some((v) => v.volume === name))
        .map((r) => r.collection_id),
    ]).size
  const attention = volumes.filter((v) => NEEDS_ATTENTION.includes(v.state))
  const used = volumes
    .filter((v) => v.available)
    .reduce((sum, v) => sum + (v.civex_used_bytes ?? 0), 0)

  function move(name: string, delta: -1 | 1) {
    const i = queueNames.indexOf(name)
    const j = i + delta
    if (i < 0 || j < 0 || j >= queueNames.length) return
    const next = [...queueNames]
    ;[next[i], next[j]] = [next[j], next[i]]
    setQueue.mutate(next)
  }

  function toggleQueue(name: string) {
    setQueue.mutate(
      queueNames.includes(name)
        ? queueNames.filter((n) => n !== name)
        : [...queueNames, name],
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <p className="max-w-prose text-sm text-fg-muted">
          Volumes are the folders — usually on separate drives — where Civex
          keeps files. {volumes.length}{' '}
          {volumes.length === 1 ? 'volume' : 'volumes'}
          {' · '}Civex uses {formatSize(used)}.
        </p>
        <Button variant="primary" size="sm" onClick={() => setAdding(true)}>
          <Plus size={14} /> Add volume
        </Button>
      </div>

      {attention.length > 0 && (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-md border border-attention-muted bg-attention-subtle px-4 py-3 text-sm text-attention"
        >
          <AlertTriangle
            size={15}
            className="mt-0.5 shrink-0"
            aria-hidden="true"
          />
          <span>
            {attention.length === 1
              ? `${attention[0].name} needs attention.`
              : `${attention.length} volumes need attention: ${attention.map((v) => v.name).join(', ')}.`}{' '}
            Files on {attention.length === 1 ? 'it' : 'them'} can&apos;t be
            opened until {attention.length === 1 ? 'it is' : 'they are'} back.
          </span>
        </div>
      )}

      {volumes.length === 0 ? (
        <EmptyState
          title="No volumes yet"
          message="Add a folder, a drive or a network share for Civex to keep files on."
        />
      ) : (
        <Table>
          <Thead>
            <Tr>
              <Th>Volume</Th>
              <Th>Status</Th>
              <Th>Space</Th>
              <Th>Write queue</Th>
              <Th>Collections</Th>
              <Th className="w-12">
                <span className="sr-only">Actions</span>
              </Th>
            </Tr>
          </Thead>
          <Tbody>
            {volumes.map((vol) => (
              <VolumeRow
                key={vol.name}
                vol={vol}
                queueIndex={queueNames.indexOf(vol.name)}
                queueLength={queueNames.length}
                collections={collectionsOn(vol.name)}
                onEdit={() => setEditing(vol)}
                onRemove={() => setRemoving(vol)}
                onAdopt={() => setAdopting(vol)}
                onMove={(delta) => move(vol.name, delta)}
                onToggleQueue={() => toggleQueue(vol.name)}
              />
            ))}
          </Tbody>
        </Table>
      )}

      <div className="rounded-md border border-border bg-canvas-subtle px-4 py-3 text-xs text-fg-muted">
        <p className="flex flex-wrap items-center gap-1">
          <span className="font-semibold text-fg">Write queue:</span>
          {queueNames.length ? (
            queueNames.map((name, i) => (
              <span key={name} className="inline-flex items-center gap-1">
                {i > 0 && <ArrowRight size={11} aria-hidden="true" />}
                {name}
              </span>
            ))
          ) : (
            <span>empty</span>
          )}
        </p>
        <p className="mt-1">
          New files go to the first volume in the queue that is online and has
          room. A volume outside the queue is only used by collections that have
          it as their home. Files that already exist are never copied again.
        </p>
      </div>

      {adding && (
        <AddVolumeModal
          existingNames={volumes.map((v) => v.name)}
          onClose={() => setAdding(false)}
        />
      )}
      {editing && (
        <EditVolumeModal vol={editing} onClose={() => setEditing(null)} />
      )}
      {removing && (
        <RemoveVolumeDialog
          vol={removing}
          homedCount={homesOf(removing.name)}
          onClose={() => setRemoving(null)}
        />
      )}
      {adopting && (
        <ConfirmDialog
          title={`Treat this drive as “${adopting.name}”?`}
          confirmLabel="Yes, this is the drive"
          isPending={adopt.isPending}
          warning={adopt.isError ? errorMessage(adopt.error) : undefined}
          body={
            <p className="text-sm text-fg">
              {adopting.reason} If this is in fact the right drive — its marker
              was deleted, or it was re-formatted — Civex rewrites the marker so
              it is recognised again. Nothing else on the drive changes.
            </p>
          }
          onConfirm={() =>
            adopt.mutate(adopting.name, { onSuccess: () => setAdopting(null) })
          }
          onClose={() => setAdopting(null)}
        />
      )}
    </div>
  )
}
