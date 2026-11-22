import { useState } from 'react'
import { fileAccessApi, type FileSelection } from '../../api/fileAccess'
import { PROJECT, useDriveChoice } from '../../hooks/useDriveChoice'
import { errorMessage } from '../../lib/errors'
import { formatSize } from '../../utils/storage'
import {
  Button,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  useToast,
} from '../ui'
import { DrivePicker } from './DrivePicker'
import { ToDownloadNotice } from './ToDownloadNotice'
import {
  copyToDrive,
  downloadZip,
  openAvailable,
  type FlowContext,
  type Problem,
} from './fileFlows'
import { UnreachableList } from './UnreachableList'

const plural = (n: number, word: string) =>
  `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`

/** The one place a person decides what to do when an export can't just be
 * made: what the selection holds, anything out of reach (with a way to check
 * again once a drive is plugged in), and going on with what is there. It never
 * asks how the files are put together (links, copies): only, for files put on
 * a drive, which drive. Going on starts the work in the background and closes
 * it. */
export function FilesDialog({
  problem,
  selection: hostSelection,
  folderName: hostFolderName,
  ctx,
  onClose,
}: {
  problem: Problem
  selection: FileSelection
  folderName: string
  ctx: FlowContext
  onClose: () => void
}) {
  const toast = useToast()
  // What was being exported when it ran into the problem (its table and choices
  // included), not just where the menu was opened.
  const selection = problem.selection ?? hostSelection
  const folderName = problem.name ?? hostFolderName
  const [plan, setPlan] = useState(problem.plan)
  const [checking, setChecking] = useState(false)
  const zip = problem.kind === 'zip'
  // A folder that can't be made where the files are (the drive can't be written
  // to) can still be put on another drive.
  const onDrive = problem.kind === 'copy' || (!zip && !!problem.message)
  const [chosen, setChosen] = useState<string | null>(null)

  const missing = plan.total - plan.available
  const drive = useDriveChoice({
    need: plan.available_bytes,
    allowProject: true,
    chosen,
  })

  async function checkAgain() {
    setChecking(true)
    try {
      setPlan(await fileAccessApi.plan(selection))
    } catch (err) {
      toast.error(errorMessage(err))
    } finally {
      setChecking(false)
    }
  }

  function go() {
    onClose()
    if (zip) return void downloadZip(ctx, selection, folderName, true)
    if (!onDrive) return void openAvailable(ctx, selection, folderName)
    void copyToDrive(
      ctx,
      selection,
      folderName,
      drive.target === PROJECT ? undefined : drive.target,
      plan.available,
    )
  }

  const title = zip
    ? 'Download these files'
    : onDrive
      ? 'Put these files on a drive'
      : 'Save these files to a folder'
  const some =
    missing > 0 ? ` the ${plan.available.toLocaleString()} available` : ''
  const label = zip
    ? `Download${some}`
    : onDrive
      ? `Put${some || ` ${plural(plan.available, 'file')}`} on ${drive.target === PROJECT ? 'the project folder' : drive.target}`
      : missing > 0
        ? `Save${some}`
        : 'Save to folder'
  const disabled =
    checking ||
    plan.available === 0 ||
    (onDrive && (drive.tooBig || !drive.target))

  return (
    <Modal onClose={onClose} size="md" dismissible={!checking}>
      <ModalHeader onClose={onClose}>{title}</ModalHeader>
      <ModalBody>
        <div className="space-y-4 text-sm">
          <ToDownloadNotice toFetch={plan.to_fetch} />
          <p className="text-fg-muted">
            {plural(plan.total, 'file')} ({formatSize(plan.bytes)}). Nothing has
            been {zip ? 'downloaded' : 'made'} yet.
          </p>

          {problem.message && (
            <p role="alert" className="text-attention">
              {problem.message}
            </p>
          )}

          {missing > 0 && (
            <section aria-label="Files that can’t be reached">
              <p className="mb-2 font-medium text-fg">
                {plural(missing, 'file')} can’t be reached
              </p>
              <UnreachableList groups={plan.unavailable} />
            </section>
          )}

          {onDrive && (
            <DrivePicker
              label="Which drive"
              value={drive.target}
              targets={drive.targets}
              allowProject
              need={plan.available_bytes}
              free={drive.free}
              tooBig={drive.tooBig}
              onChange={setChosen}
            />
          )}
        </div>
      </ModalBody>
      <ModalFooter>
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        {missing > 0 && (
          <Button onClick={() => void checkAgain()} disabled={checking}>
            {checking ? 'Checking…' : 'Check again'}
          </Button>
        )}
        <Button variant="primary" onClick={go} disabled={disabled}>
          {label}
        </Button>
      </ModalFooter>
    </Modal>
  )
}
