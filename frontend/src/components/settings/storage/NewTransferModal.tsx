import { useState } from 'react'
import type { TransferSpec } from '../../../api/transfers'
import { useCollections } from '../../../hooks/useCollections'
import {
  useStartTransfer,
  useTransferPreview,
} from '../../../hooks/useTransfers'
import { useVolumes } from '../../../hooks/useStore'
import { useUISettings } from '../../../hooks/useUISettings'
import { errorMessage } from '../../../lib/errors'
import { formatSize } from '../../../utils/storage'
import { Button, Modal, ModalBody, ModalFooter, ModalHeader } from '../../ui'

export interface TransferPreset {
  /** Volume to empty. */
  source?: string
  /** Collection to gather. */
  collectionId?: string
}

/** Choose what to move and where, see exactly what it would do, then start it. */
export function NewTransferModal({
  preset,
  onClose,
}: {
  preset: TransferPreset
  onClose: () => void
}) {
  const { data: volumes = [] } = useVolumes()
  const { data: collections = [] } = useCollections()
  const advanced = useUISettings().data?.show_advanced ?? false
  const start = useStartTransfer()
  const [kind, setKind] = useState<'drain' | 'consolidate'>(
    preset.collectionId ? 'consolidate' : 'drain',
  )
  const [source, setSource] = useState(preset.source ?? '')
  const [collectionId, setCollectionId] = useState(preset.collectionId ?? '')
  const [target, setTarget] = useState('')
  const [includeShared, setIncludeShared] = useState(false)
  const [verifyFull, setVerifyFull] = useState(false)
  const [freeze, setFreeze] = useState(true)

  const ready = target && (kind === 'drain' ? source : collectionId)
  const spec: TransferSpec | null = ready
    ? {
        kind,
        targets: [target],
        sources: kind === 'drain' ? [source] : [],
        collection_ids: kind === 'consolidate' ? [collectionId] : [],
        include_shared: includeShared,
        verify: verifyFull ? 'full' : 'copy',
        freeze_sources: freeze,
      }
    : null
  const preview = useTransferPreview(spec)
  const plan = preview.data

  return (
    <Modal onClose={onClose} size="lg" dismissible={!start.isPending}>
      <ModalHeader onClose={onClose}>Move files</ModalHeader>
      <ModalBody>
        <div className="space-y-4 text-sm">
          <fieldset className="flex gap-4">
            <legend className="sr-only">What to move</legend>
            {(['drain', 'consolidate'] as const).map((k) => (
              <label key={k} className="flex items-center gap-2">
                <input
                  type="radio"
                  checked={kind === k}
                  onChange={() => setKind(k)}
                />
                {k === 'drain' ? 'Empty a volume' : 'Gather a collection'}
              </label>
            ))}
          </fieldset>

          {kind === 'drain' ? (
            <label className="block">
              <span className="text-fg-muted">Move everything off</span>
              <select
                className="mt-1 block w-full rounded-md border border-border bg-canvas px-2 py-1.5 text-fg"
                value={source}
                onChange={(e) => setSource(e.target.value)}
              >
                <option value="">Choose a volume…</option>
                {volumes.map((v) => (
                  <option key={v.name} value={v.name}>
                    {v.name}
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <label className="block">
              <span className="text-fg-muted">Collection</span>
              <select
                className="mt-1 block w-full rounded-md border border-border bg-canvas px-2 py-1.5 text-fg"
                value={collectionId}
                onChange={(e) => setCollectionId(e.target.value)}
              >
                <option value="">Choose a collection…</option>
                {collections.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
          )}

          <label className="block">
            <span className="text-fg-muted">Put the files on</span>
            <select
              className="mt-1 block w-full rounded-md border border-border bg-canvas px-2 py-1.5 text-fg"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
            >
              <option value="">Choose a volume…</option>
              {volumes
                .filter((v) => kind !== 'drain' || v.name !== source)
                .map((v) => (
                  <option key={v.name} value={v.name} disabled={!v.available}>
                    {v.name}
                    {v.disk_free_bytes != null
                      ? ` — ${formatSize(v.disk_free_bytes)} free`
                      : ''}
                    {!v.available ? ' (not available)' : ''}
                  </option>
                ))}
            </select>
          </label>

          {kind === 'consolidate' && (
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={includeShared}
                onChange={(e) => setIncludeShared(e.target.checked)}
              />
              Also move files that other collections use
            </label>
          )}
          {kind === 'drain' && (
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={freeze}
                onChange={(e) => setFreeze(e.target.checked)}
              />
              Make the volume read-only while it runs (restored afterwards)
            </label>
          )}
          {advanced && (
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={verifyFull}
                onChange={(e) => setVerifyFull(e.target.checked)}
              />
              Read each copy back and check it (slower)
            </label>
          )}

          <section
            aria-live="polite"
            className="rounded-md bg-canvas-inset p-3"
          >
            {!spec && (
              <p className="text-fg-muted">
                Choose what to move and where to see what it would do.
              </p>
            )}
            {spec && preview.isError && (
              <p className="text-danger">{errorMessage(preview.error)}</p>
            )}
            {plan && (
              <div className="space-y-1">
                <p className="font-medium text-fg">
                  {plan.files} files ({formatSize(plan.bytes)}) would move
                  {plan.already_there > 0 &&
                    `; ${plan.already_there} already there`}
                  .
                </p>
                {plan.shared_left > 0 && (
                  <p className="text-fg-muted">
                    {plan.shared_left} files (
                    {formatSize(plan.shared_left_bytes)}) stay, because other
                    collections use them.
                  </p>
                )}
                {plan.warnings.map((w) => (
                  <p key={w} className="text-attention">
                    {w}
                  </p>
                ))}
                {plan.problems.map((w) => (
                  <p key={w} className="text-danger">
                    {w}
                  </p>
                ))}
              </div>
            )}
          </section>
          {start.isError && (
            <p className="text-danger">{errorMessage(start.error)}</p>
          )}
        </div>
      </ModalBody>
      <ModalFooter>
        <Button onClick={onClose} disabled={start.isPending}>
          Cancel
        </Button>
        <Button
          variant="primary"
          disabled={!spec || !plan?.can_proceed || start.isPending}
          onClick={() => spec && start.mutate(spec, { onSuccess: onClose })}
        >
          Start moving
        </Button>
      </ModalFooter>
    </Modal>
  )
}
