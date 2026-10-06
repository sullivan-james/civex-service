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
import {
  copyToDrive,
  downloadZip,
  moveThenOpen,
  openAvailable,
  type FlowContext,
  type Problem,
} from './fileFlows'
import { UnreachableList } from './UnreachableList'

type How = 'link' | 'move' | 'copy'

const plural = (n: number, word: string) =>
  `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`

/** The one place a person decides what to do about their files: what the
 * selection holds, anything out of reach (with a way to check again once a drive
 * is plugged in), and how to get a folder anyway. Everything is in this one
 * dialog, so choosing never opens another; the choice starts the work in the
 * background and closes it. */
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
  const scattered = !zip && plan.scattered
  // The server said a linked folder can't be made there: start from a copy.
  const [picked, setPicked] = useState<How>(
    problem.kind === 'copy' || problem.message ? 'copy' : 'link',
  )
  // Files on several drives can't be linked as one folder; once they are on one
  // (moved, or a drive came back) there is nothing to move.
  const how: How =
    picked === 'link' && scattered
      ? 'move'
      : picked === 'move' && !scattered
        ? 'link'
        : picked
  const [chosen, setChosen] = useState<string | null>(null)

  const missing = plan.total - plan.available
  const holding = plan.by_volume[0]?.volume
  const there = plan.by_volume.find((v) => v.volume === (chosen ?? holding))
  const moving = how === 'move'
  const need = moving
    ? plan.available_bytes - (there?.bytes ?? 0)
    : plan.available_bytes
  const drive = useDriveChoice({
    holding,
    need,
    allowProject: how === 'copy',
    chosen: chosen === PROJECT && moving ? null : chosen,
  })
  const moveFiles = plan.available - (there?.files ?? 0)

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
    if (how === 'link') return void openAvailable(ctx, selection, folderName)
    if (how === 'move')
      return void moveThenOpen(ctx, selection, folderName, drive.target)
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
    : problem.kind === 'copy'
      ? 'Copy these files to a drive'
      : 'Open these files as a folder'
  const label = zip
    ? `Download the ${plan.available.toLocaleString()} available`
    : how === 'link'
      ? missing > 0
        ? `Open the ${plan.available.toLocaleString()} available`
        : 'Open folder'
      : how === 'move'
        ? `Move ${plural(Math.max(moveFiles, 0), 'file')} and open`
        : `Copy ${plural(plan.available, 'file')} (${formatSize(plan.available_bytes)})`
  const disabled =
    checking ||
    plan.available === 0 ||
    (!zip && how !== 'link' && (drive.tooBig || !drive.target)) ||
    (how === 'move' && moveFiles <= 0)

  return (
    <Modal onClose={onClose} size="md" dismissible={!checking}>
      <ModalHeader onClose={onClose}>{title}</ModalHeader>
      <ModalBody>
        <div className="space-y-4 text-sm">
          <p className="text-fg-muted">
            {plural(plan.total, 'file')} ({formatSize(plan.bytes)})
            {plan.by_volume.length > 0 && (
              <>
                {' '}
                on{' '}
                {plan.by_volume
                  .map((v) => `${v.volume} (${v.files.toLocaleString()})`)
                  .join(', ')}
              </>
            )}
            . Nothing has been {zip ? 'downloaded' : 'opened'} yet.
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

          {!zip && (
            <fieldset className="space-y-2">
              <legend className="mb-1 font-medium text-fg">
                How do you want them?
              </legend>
              <Choice
                checked={how === 'link'}
                disabled={scattered}
                onChange={() => setPicked('link')}
                title="Link them where they are"
                hint={
                  scattered
                    ? `They are on ${plan.by_volume.length} drives, and a linked folder has to be on one.`
                    : 'Nothing is copied. The folder is made on the drive that holds the files.'
                }
              />
              {scattered && (
                <Choice
                  checked={how === 'move'}
                  onChange={() => setPicked('move')}
                  title="Move them onto one drive, then link"
                  hint="Moves only these files, not the rest of their collections."
                />
              )}
              <Choice
                checked={how === 'copy'}
                onChange={() => setPicked('copy')}
                title="Copy them onto a drive"
                hint={`Real copies you can edit. Uses ${formatSize(plan.available_bytes)}.`}
              />
            </fieldset>
          )}

          {!zip && how !== 'link' && (
            <DrivePicker
              label={how === 'move' ? 'Move them onto' : 'Copy onto'}
              value={drive.target}
              targets={drive.targets}
              allowProject={how === 'copy'}
              need={need}
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

function Choice({
  checked,
  disabled,
  onChange,
  title,
  hint,
}: {
  checked: boolean
  disabled?: boolean
  onChange: () => void
  title: string
  hint: string
}) {
  return (
    <label className={`flex items-start gap-2 ${disabled ? 'opacity-60' : ''}`}>
      <input
        type="radio"
        className="mt-1"
        checked={checked}
        disabled={disabled}
        onChange={onChange}
      />
      <span>
        <span className="block text-fg">{title}</span>
        <span className="block text-xs text-fg-muted">{hint}</span>
      </span>
    </label>
  )
}
