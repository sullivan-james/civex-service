import { useState } from 'react'
import { AlertTriangle } from '../ui/icons'
import { Button, Field, Select } from '../ui'
import type { PlacementPolicy } from '../../api/store'
import {
  useClearPlacement,
  usePlacements,
  useSetPlacement,
  useVolumes,
} from '../../hooks/useStore'
import { errorMessage } from '../../lib/errors'
import { CollectionFileLocations } from './CollectionFileLocations'

const NONE = ''

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

/** Where this collection's files are and where its new files are written. */
export function CollectionStorage({ collectionId }: { collectionId: string }) {
  const { data: volumes = [] } = useVolumes()
  const { data: placements = [] } = usePlacements()
  const setPlacement = useSetPlacement()
  const clearPlacement = useClearPlacement()

  const current = placements.find((p) => p.collection_id === collectionId)
  const [draftVolume, setDraftVolume] = useState<string | null>(null)
  const [draftPolicy, setDraftPolicy] = useState<PlacementPolicy | null>(null)

  const volume = draftVolume ?? current?.volume ?? NONE
  const policy = draftPolicy ?? current?.on_unavailable ?? 'spill'
  const dirty =
    volume !== (current?.volume ?? NONE) ||
    (volume !== NONE && policy !== (current?.on_unavailable ?? 'spill'))
  const home = volumes.find((v) => v.name === current?.volume)
  const error = setPlacement.error ?? clearPlacement.error

  function save() {
    const done = () => {
      setDraftVolume(null)
      setDraftPolicy(null)
    }
    if (volume === NONE) {
      clearPlacement.mutate(collectionId, { onSuccess: done })
    } else {
      setPlacement.mutate(
        { collectionId, volume, onUnavailable: policy },
        { onSuccess: done },
      )
    }
  }

  return (
    <div className="max-w-xl space-y-4">
      <CollectionFileLocations
        collectionId={collectionId}
        home={current?.volume}
      />

      <Field
        label="Home volume"
        info="Which volume receives this collection's new files. A file whose content is already stored, on any volume, is reused where it is and never copied again."
      >
        <Select value={volume} onChange={(e) => setDraftVolume(e.target.value)}>
          <option value={NONE}>General write order (default)</option>
          {volumes.map((v) => (
            <option key={v.name} value={v.name}>
              {v.name}
              {v.state !== 'online' ? ` — ${v.state.replace('_', ' ')}` : ''}
            </option>
          ))}
        </Select>
      </Field>

      {volume !== NONE && (
        <Field label="If the home volume can't take a file">
          <Select
            value={policy}
            onChange={(e) => setDraftPolicy(e.target.value as PlacementPolicy)}
          >
            <option value="spill">Use the general write order instead</option>
            <option value="fail">Refuse the upload</option>
          </Select>
        </Field>
      )}

      {home && home.state !== 'online' && (
        <p className="flex items-start gap-1.5 text-xs text-attention">
          <AlertTriangle size={13} className="shrink-0 mt-0.5" />
          {home.reason || `The home volume is ${home.state}.`}
        </p>
      )}

      {error != null && (
        <p role="alert" className="text-xs text-danger">
          {errorMessage(error)}
        </p>
      )}

      <div className="flex items-center gap-4">
        <Button
          size="sm"
          variant="primary"
          disabled={
            !dirty || setPlacement.isPending || clearPlacement.isPending
          }
          onClick={save}
        >
          Save
        </Button>
        <Button size="sm" variant="link" to="/settings/storage?tab=collections">
          All collections
        </Button>
      </div>
    </div>
  )
}
