import { useIsDesktop } from '../../../hooks/useIsDesktop'
import { useState } from 'react'
import type { VolumeStats } from '../../../api/store'
import { useUpdateVolume } from '../../../hooks/useStore'
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
} from '../../ui'
import { errorMessage } from '../../../lib/errors'
import { browseFolderDesktop } from '../../../utils/nativeFolder'
import { VolumeStatus } from '../../files/Where'
import { FolderPickerModal } from '../FolderPickerModal'

/** Change a volume's folder or space limit. The folder is only repointed:
 * no files are moved. */
export function EditVolumeModal({
  vol,
  onClose,
}: {
  vol: VolumeStats
  onClose: () => void
}) {
  const isDesktop = useIsDesktop()
  const updateVolume = useUpdateVolume()
  const [path, setPath] = useState(vol.path)
  const [limitOn, setLimitOn] = useState(vol.allocated_gb != null)
  const [limitGb, setLimitGb] = useState(
    vol.allocated_gb != null ? String(vol.allocated_gb) : '',
  )
  const [picking, setPicking] = useState(false)

  const cleanPath = path.trim().replace(/\\/g, '/')
  const limit = limitOn && limitGb !== '' ? Number(limitGb) : undefined
  const limitInvalid = limitOn && !(limit !== undefined && limit > 0)
  const pathChanged = cleanPath !== vol.path
  const limitChanged = limitOn
    ? limit !== vol.allocated_gb
    : vol.allocated_gb != null
  const canSave =
    cleanPath !== '' &&
    !limitInvalid &&
    (pathChanged || limitChanged) &&
    !updateVolume.isPending

  function save() {
    updateVolume.mutate(
      {
        name: vol.name,
        body: {
          ...(pathChanged ? { path: cleanPath } : {}),
          ...(limitOn && limitChanged ? { allocated_gb: limit } : {}),
          ...(!limitOn && vol.allocated_gb != null
            ? { clear_allocation: true }
            : {}),
        },
      },
      { onSuccess: onClose },
    )
  }

  return (
    <Modal onClose={onClose} size="lg" dismissible={!updateVolume.isPending}>
      <ModalHeader onClose={onClose}>Edit volume “{vol.name}”</ModalHeader>
      <ModalBody>
        <div className="space-y-5">
          <p className="text-sm">
            <VolumeStatus state={vol.state} reason={vol.reason} fix={vol.fix} />
          </p>

          <div className="space-y-2">
            <div className="flex items-end gap-2">
              <Field label="Folder" className="flex-1">
                <Input
                  value={path}
                  onChange={(e) => setPath(e.target.value)}
                  className="font-mono"
                />
              </Field>
              <Button onClick={() => setPicking(true)}>Browse…</Button>
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
            <InfoTip>
              This points the volume at a different folder. It does not move any
              files: Civex looks for them in the new folder.
            </InfoTip>
          </div>

          <div className="space-y-1">
            <label className="flex cursor-pointer items-center gap-2 text-sm text-fg">
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
              </div>
            )}
          </div>

          {updateVolume.isError && (
            <p
              role="alert"
              className="rounded-md border border-danger-muted bg-danger-subtle px-3 py-2 text-xs text-danger"
            >
              {errorMessage(updateVolume.error)}
            </p>
          )}
        </div>

        {picking && (
          <FolderPickerModal
            initialPath={cleanPath}
            onSelect={(chosen) => setPath(chosen)}
            onClose={() => setPicking(false)}
          />
        )}
      </ModalBody>
      <ModalFooter>
        <Button onClick={onClose} disabled={updateVolume.isPending}>
          Cancel
        </Button>
        <Button variant="primary" onClick={save} disabled={!canSave}>
          {updateVolume.isPending ? 'Saving…' : 'Save'}
        </Button>
      </ModalFooter>
    </Modal>
  )
}
