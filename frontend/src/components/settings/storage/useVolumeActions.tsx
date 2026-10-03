import { useState, type ReactNode } from 'react'
import type { VolumeStats } from '../../../api/store'
import {
  useAdoptVolume,
  usePlacements,
  useSetQueue,
  useVolumes,
} from '../../../hooks/useStore'
import { errorMessage } from '../../../lib/errors'
import { ConfirmDialog } from '../../ui'
import { EditVolumeModal } from './EditVolumeModal'
import { RemoveVolumeDialog } from './RemoveVolumeDialog'

/** What can be done to a volume (edit, remove, re-recognise a drive, change its
 * place in the write queue), shared by the volume list and a volume's own page
 * so neither has its own copy. `dialogs` must be rendered by the caller. */
export function useVolumeActions(onRemoved?: () => void) {
  const { data: volumes = [] } = useVolumes()
  const { data: placements = [] } = usePlacements()
  const setQueue = useSetQueue()
  const adopt = useAdoptVolume()
  const [editing, setEditing] = useState<VolumeStats | null>(null)
  const [removing, setRemoving] = useState<VolumeStats | null>(null)
  const [adopting, setAdopting] = useState<VolumeStats | null>(null)

  const queueNames = volumes.filter((v) => v.in_queue).map((v) => v.name)

  function moveInQueue(name: string, delta: -1 | 1) {
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

  const dialogs: ReactNode = (
    <>
      {editing && (
        <EditVolumeModal vol={editing} onClose={() => setEditing(null)} />
      )}
      {removing && (
        <RemoveVolumeDialog
          vol={removing}
          homedCount={
            placements.filter((p) => p.volume === removing.name).length
          }
          onClose={() => {
            setRemoving(null)
            // Gone from the list now, so a page about it has nothing to show.
            if (!volumes.some((v) => v.name === removing.name)) onRemoved?.()
          }}
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
    </>
  )

  return {
    queueNames,
    moveInQueue,
    toggleQueue,
    edit: setEditing,
    remove: setRemoving,
    adopt: setAdopting,
    dialogs,
  }
}
