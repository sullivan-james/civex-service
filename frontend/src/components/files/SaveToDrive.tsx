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
import { FolderOpen } from '../ui/icons'
import { useStored } from '../../hooks/useStored'
import { FolderPickerModal } from '../settings/FolderPickerModal'
import { saveCopy } from './fileFlows'

export type SaveHow = 'folder' | 'download'

/** Where one file civex makes goes (a copy of the project, a release's):
 * into a folder of this computer, which is where civex runs, or through the
 * browser as a download. The folder is any folder, chosen with the app's own
 * folder browser (an external drive, a shared folder: it need not be one of
 * the project's drives), and the last one used is remembered. The one choice
 * both dialogs offer. */
export function useSaveChoice() {
  const [how, setHow] = useState<SaveHow>('folder')
  const [folder, setFolder] = useStored<string | null>('save.folder', null)
  const [browsing, setBrowsing] = useState(false)
  return {
    how,
    /** The folder to send to the server. */
    folder,
    /** Nothing to save into yet. */
    blocked: how === 'folder' && !folder,
    picker: (
      <div className="space-y-3">
        <SegmentedControl
          size="sm"
          label="Where it goes"
          value={how}
          onChange={setHow}
          options={[
            { value: 'folder', label: 'Save to a folder' },
            { value: 'download', label: 'Download' },
          ]}
        />
        {how === 'folder' && (
          <div className="flex items-center gap-2">
            <FolderOpen
              size={14}
              className="shrink-0 text-fg-muted"
              aria-hidden="true"
            />
            <span
              className="min-w-0 flex-1 truncate font-mono text-xs"
              title={folder ?? undefined}
            >
              {folder ?? 'No folder chosen'}
            </span>
            <Button size="sm" onClick={() => setBrowsing(true)}>
              Choose…
            </Button>
          </div>
        )}
        {browsing && (
          <FolderPickerModal
            initialPath={folder ?? undefined}
            onSelect={setFolder}
            onClose={() => setBrowsing(false)}
          />
        )}
      </div>
    ),
  }
}

/** A small dialog for that choice alone: save it to a folder, or download
 * it. Saving runs in the background (`fileFlows.saveCopy`): the dialog closes
 * at once and the status bar shows it. */
export function SaveToDriveDialog({
  title,
  onSave,
  onDownload,
  onClose,
}: {
  title: string
  /** Write it into the folder; answers the path. */
  onSave: (folder: string, progressId: string) => Promise<{ path: string }>
  onDownload: () => void
  onClose: () => void
}) {
  const toast = useToast()
  const qc = useQueryClient()
  const choice = useSaveChoice()

  function go() {
    if (choice.how === 'download') onDownload()
    else if (choice.folder) {
      const folder = choice.folder
      void saveCopy(
        { toast, qc, problem: () => undefined },
        'Saving a copy…',
        (progressId) => onSave(folder, progressId),
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
          {choice.how === 'folder' ? 'Save' : 'Download'}
        </Button>
      </ModalFooter>
    </Modal>
  )
}
