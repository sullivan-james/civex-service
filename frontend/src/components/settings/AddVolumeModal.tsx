import { useState, type ReactNode } from 'react'
import { useAddVolume, useInspectPath } from '../../hooks/useStore'
import { useDebouncedValue } from '../../hooks/useDebouncedValue'
import {
  Button,
  Checkbox,
  Field,
  InfoTip,
  Input,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
} from '../ui'
import { errorMessage } from '../../lib/errors'
import { browseFolderDesktop, isDesktop } from '../../utils/nativeFolder'
import { formatSize } from '../../utils/storage'
import { FolderBrowser } from './FolderBrowser'
import { PathCheck } from './PathCheck'

const NAME_RE = /^[A-Za-z0-9_-]+$/

function Step({
  n,
  title,
  info,
  children,
}: {
  n: number
  title: string
  info?: string
  children: ReactNode
}) {
  return (
    <section className="flex gap-3 py-5 first:pt-0 last:pb-0 border-t border-border first:border-t-0">
      <div
        aria-hidden="true"
        className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent-subtle text-xs font-semibold text-accent"
      >
        {n}
      </div>
      <div className="min-w-0 flex-1 space-y-3">
        <h3 className="flex items-center gap-1 text-sm font-semibold text-fg">
          {title}
          {info && <InfoTip>{info}</InfoTip>}
        </h3>
        {children}
      </div>
    </section>
  )
}

/** Add a storage volume: a name, a folder (picked from the machine's own
 * folders, with a live check of what adding it involves), and how it is used. */
export function AddVolumeModal({
  existingNames,
  onClose,
}: {
  existingNames: string[]
  onClose: () => void
}) {
  const addVolume = useAddVolume()
  const [view, setView] = useState<'form' | 'browse'>('form')
  const [name, setName] = useState('')
  const [path, setPath] = useState('')
  const [limitOn, setLimitOn] = useState(false)
  const [limitGb, setLimitGb] = useState('')
  const [joinQueue, setJoinQueue] = useState(false)

  const trimmedPath = path.trim().replace(/\\/g, '/')
  const settledPath = useDebouncedValue(trimmedPath, 400)
  const inspect = useInspectPath(settledPath)
  const inspection = settledPath === trimmedPath ? inspect.data : undefined
  const checking =
    trimmedPath !== '' && (settledPath !== trimmedPath || inspect.isFetching)

  const trimmedName = name.trim()
  const nameError =
    trimmedName === ''
      ? undefined
      : !NAME_RE.test(trimmedName)
        ? 'Use only letters, digits, hyphens and underscores.'
        : existingNames.includes(trimmedName)
          ? `A volume called '${trimmedName}' already exists.`
          : undefined
  const limit = limitOn && limitGb !== '' ? Number(limitGb) : undefined
  const limitInvalid = limitOn && !(limit !== undefined && limit > 0)
  const blocked = (inspection?.problems.length ?? 0) > 0

  const canAdd =
    trimmedName !== '' &&
    !nameError &&
    trimmedPath !== '' &&
    !checking &&
    !!inspection &&
    !blocked &&
    !limitInvalid &&
    !addVolume.isPending

  function submit() {
    if (!canAdd) return
    addVolume.mutate(
      {
        name: trimmedName,
        path: trimmedPath,
        allocated_gb: limit,
        add_to_queue: joinQueue,
      },
      { onSuccess: onClose },
    )
  }

  if (view === 'browse')
    return (
      <Modal onClose={onClose} size="xl">
        <ModalHeader onClose={onClose}>Choose a folder</ModalHeader>
        <FolderBrowser
          initialPath={inspection?.is_dir ? inspection.path : undefined}
          onCancel={() => setView('form')}
          onSelect={(chosen) => {
            setPath(chosen)
            setView('form')
          }}
        />
      </Modal>
    )

  const summary = [
    trimmedName ? `Adds “${trimmedName}”` : 'Adds a volume',
    trimmedPath ? `at ${trimmedPath}` : null,
    inspection?.is_network ? '(network drive)' : null,
    limit && limit > 0 ? `· limit ${limit} GB` : null,
    joinQueue ? '· in the write queue' : null,
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <Modal onClose={onClose} size="lg" dismissible={!addVolume.isPending}>
      <ModalHeader onClose={onClose}>Add a volume</ModalHeader>
      <ModalBody>
        <Step
          n={1}
          title="Name"
          info="How you refer to it in commands and settings."
        >
          <Field
            label="Volume name"
            info="Letters, digits, hyphens and underscores."
            error={nameError}
            required
          >
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. archive"
              autoFocus
            />
          </Field>
        </Step>

        <Step
          n={2}
          title="Location"
          info="A drive that is plugged in, or a network share already mounted on this computer (Civex doesn't mount shares itself)."
        >
          <div className="flex items-end gap-2">
            <Field label="Folder" className="flex-1" required>
              <Input
                value={path}
                onChange={(e) => setPath(e.target.value)}
                placeholder="/media/archive-drive/civex"
                className="font-mono"
              />
            </Field>
            <Button onClick={() => setView('browse')}>Browse…</Button>
            {isDesktop && (
              <Button
                onClick={async () => {
                  const chosen = await browseFolderDesktop()
                  if (chosen) setPath(chosen)
                }}
              >
                System dialog…
              </Button>
            )}
          </div>
          <PathCheck
            inspection={inspection}
            checking={checking}
            error={
              inspect.isError && settledPath === trimmedPath
                ? inspect.error
                : null
            }
          />
        </Step>

        <Step n={3} title="How it is used">
          <div className="space-y-1">
            <label className="flex items-center gap-2 text-sm text-fg cursor-pointer">
              <Checkbox
                checked={limitOn}
                onChange={(e) => setLimitOn(e.target.checked)}
              />
              Limit how much space Civex may use
            </label>
            {limitOn && (
              <div className="ml-6 flex items-center gap-2">
                <Input
                  type="number"
                  min="0.1"
                  step="0.1"
                  aria-label="Space limit in GB"
                  value={limitGb}
                  onChange={(e) => setLimitGb(e.target.value)}
                  className="w-32"
                />
                <span className="text-sm text-fg-muted">GB</span>
                {inspection?.free_bytes != null && (
                  <span className="text-xs text-fg-muted">
                    ({formatSize(inspection.free_bytes)} free on this drive)
                  </span>
                )}
              </div>
            )}
          </div>

          <div className="space-y-1">
            <label className="flex items-center gap-2 text-sm text-fg cursor-pointer">
              <Checkbox
                checked={joinQueue}
                onChange={(e) => setJoinQueue(e.target.checked)}
              />
              Use it for new files in general
              <InfoTip>
                Adds it to the write queue. Leave it off for a drive kept for
                particular collections (their home).
              </InfoTip>
            </label>
          </div>
        </Step>

        {addVolume.isError && (
          <p
            role="alert"
            className="mt-4 rounded-md border border-danger-muted bg-danger-subtle px-3 py-2 text-xs text-danger"
          >
            {errorMessage(addVolume.error)}
          </p>
        )}
      </ModalBody>
      <ModalFooter>
        <p className="mr-auto self-center text-xs text-fg-muted truncate">
          {summary}
        </p>
        <Button onClick={onClose} disabled={addVolume.isPending}>
          Cancel
        </Button>
        <Button variant="primary" onClick={submit} disabled={!canAdd}>
          {addVolume.isPending ? 'Adding…' : 'Add volume'}
        </Button>
      </ModalFooter>
    </Modal>
  )
}
