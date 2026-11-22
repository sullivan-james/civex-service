import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  Button,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  SegmentedControl,
  useToast,
} from '../ui'
import { PROJECT, useDriveChoice } from '../../hooks/useDriveChoice'
import { saveCopy } from './fileFlows'
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

/** A small dialog for that choice alone: put it on a drive, or download it.
 * Putting it on a drive runs in the background (`fileFlows.saveCopy`): the
 * dialog closes at once and the status bar shows it. */
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
  onSave: (
    volume: string | null,
    progressId: string,
  ) => Promise<{ path: string }>
  onDownload: () => void
  onClose: () => void
}) {
  const toast = useToast()
  const qc = useQueryClient()
  const choice = useSaveChoice(need)

  function go() {
    if (choice.how === 'download') onDownload()
    else {
      const volume = choice.volume
      void saveCopy(
        { toast, qc, problem: () => undefined },
        'Saving a copy…',
        (progressId) => onSave(volume, progressId),
      )
    }
    onClose()
  }

  return (
    <Modal onClose={onClose} size="sm">
      <ModalHeader onClose={onClose}>{title}</ModalHeader>
      <ModalBody className="space-y-3 text-sm">{choice.picker}</ModalBody>
      <ModalFooter>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={choice.blocked} onClick={go}>
          {choice.how === 'drive' ? 'Save' : 'Download'}
        </Button>
      </ModalFooter>
    </Modal>
  )
}
