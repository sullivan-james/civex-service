import { useState } from 'react'
import { Link } from 'react-router'
import { AlertTriangle } from '../ui/icons'
import { Button, CollapsibleSection, Field, Select } from '../ui'
import type { PlacementPolicy } from '../../api/store'
import {
  useClearPlacement,
  useCollectionStorage,
  usePlacements,
  useSetPlacement,
  useVolumes,
} from '../../hooks/useStore'
import { errorMessage } from '../../lib/errors'
import { CollectionFileLocations } from './CollectionFileLocations'

const NONE = ''

/** Where this collection's new files are written. Shown only once there is a
 * choice to make (a second volume exists) or a home is already set, so a
 * single-volume project never sees it. */
export function CollectionStorage({ collectionId }: { collectionId: string }) {
  const { data: volumes = [] } = useVolumes()
  const { data: placements = [] } = usePlacements()
  const setPlacement = useSetPlacement()
  const clearPlacement = useClearPlacement()
  // The same query the locations block uses (one request, shared by the cache).
  const spread = useCollectionStorage(collectionId)

  const current = placements.find((p) => p.collection_id === collectionId)
  const [draftVolume, setDraftVolume] = useState<string | null>(null)
  const [draftPolicy, setDraftPolicy] = useState<PlacementPolicy | null>(null)

  if (volumes.length < 2 && !current) return null
  // Wait, so the section opens by itself when the files are split.
  if (spread.isPending) return null
  const split = (spread.data?.volumes.length ?? 0) > 1

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
    <CollapsibleSection title="Storage" defaultOpen={!!current || split}>
      <div className="mt-2 space-y-3 max-w-xl">
        <CollectionFileLocations
          collectionId={collectionId}
          home={current?.volume}
        />

        <p className="text-sm text-fg-muted">
          Choose which volume receives this collection&apos;s new files. This
          only decides where new files are written: a file whose content is
          already stored — on any volume — is reused where it is, never copied
          again.
        </p>

        <Field label="Home volume">
          <Select
            value={volume}
            onChange={(e) => setDraftVolume(e.target.value)}
          >
            <option value={NONE}>General write queue (default)</option>
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
              onChange={(e) =>
                setDraftPolicy(e.target.value as PlacementPolicy)
              }
            >
              <option value="spill">Use the general write queue instead</option>
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
          <Link
            to="/settings/storage?tab=collections"
            className="text-sm text-accent hover:underline"
          >
            Manage all collections&apos; homes
          </Link>
        </div>
      </div>
    </CollapsibleSection>
  )
}
