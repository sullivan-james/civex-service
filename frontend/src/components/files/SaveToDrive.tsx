import { useState } from 'react'
import {
  Button,
  FormError,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  SegmentedControl,
  useToast,
} from '../ui'
import { PROJECT, useDriveChoice } from '../../hooks/useDriveChoice'
import { errorMessage } from '../../lib/errors'
import { DrivePicker } from './DrivePicker'

export type SaveHow = 'drive' | 'download'

/** Where one file civex makes goes (a copy of the project, a release's):
 * onto a drive of this computer, which is where civex runs, or through the
 * browser as a download. The one choice both dialogs offer. */
export function useSaveChoice(need: number) {
  const [how, setHow] = useState<SaveHow>('drive')
  const [chosen, setChosen] = useState<string | null>(null)
  const drive = useDriveChoice({ need, allowProject: true, chosen })
  return {
    how,
    /** The drive to send to the server (none: the project folder). */
    volume: drive.target === PROJECT ? null : drive.target,
    blocked: how === 'drive' && drive.tooBig,
    picker: (
      <div className="space-y-3">
        <SegmentedControl
          size="sm"
          label="Where it goes"
          value={how}
          onChange={setHow}
          options={[
            { value: 'drive', label: 'Put on a drive' },
            { value: 'download', label: 'Download' },
          ]}
        />
        {how === 'drive' && (
          <DrivePicker
            label="Drive"
            value={drive.target}
            targets={drive.targets}
            allowProject
            need={need}
            free={drive.free}
            tooBig={drive.tooBig}
            onChange={setChosen}
          />
        )}
      </div>
    ),
  }
}

/** A small dialog for that choice alone: put it on a drive, or download it. */
export function SaveToDriveDialog({
  title,
  need,
  onSave,
  onDownload,
  onClose,
}: {
  title: string
  /** Its size in bytes, to check the drive has room. */
  need: number
  /** Write it onto the drive (none: the project folder); answers the path. */
  onSave: (volume: string | null) => Promise<{ path: string }>
  onDownload: () => void
  onClose: () => void
}) {
  const toast = useToast()
  const choice = useSaveChoice(need)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)

  async function go() {
    if (choice.how === 'download') {
      onDownload()
      return onClose()
    }
    setBusy(true)
    setError(null)
    try {
      const saved = await onSave(choice.volume)
      toast.success(`Saved: ${saved.path}`)
      onClose()
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal onClose={onClose} size="sm" dismissible={!busy}>
      <ModalHeader onClose={onClose}>{title}</ModalHeader>
      <ModalBody className="space-y-3 text-sm">
        {choice.picker}
        {error != null && <FormError message={errorMessage(error)} />}
      </ModalBody>
      <ModalFooter>
        <Button onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button
          variant="primary"
          disabled={busy || choice.blocked}
          onClick={go}
        >
          {busy ? 'Saving…' : choice.how === 'drive' ? 'Save' : 'Download'}
        </Button>
      </ModalFooter>
    </Modal>
  )
}
