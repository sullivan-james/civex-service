import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fileAccessApi,
  type FilePick,
  type MovePlan,
} from '../../api/fileAccess'
import { PROJECT, useDriveChoice } from '../../hooks/useDriveChoice'
import { useFileListing } from '../../hooks/useFileListing'
import { useVolumes } from '../../hooks/useStore'
import { placeLabel } from '../../utils/places'
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
import { moveFiles } from './fileFlows'
import { ToDownloadNotice } from './ToDownloadNotice'

/** **Move to drive…**: a button opening the move dialog for some files (the
 * ticked files of a list, a record and what is beneath it, ticked records).
 * The one way files are moved onto a drive from a page. */
export function MoveToDriveButton({
  what,
  pick,
  onStarted,
  label = 'Move to drive…',
}: {
  what: string
  pick: FilePick
  onStarted?: () => void
  label?: string
}) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)}>
        {label}
      </Button>
      {open && (
        <MoveDialog
          what={what}
          pick={pick}
          onClose={() => setOpen(false)}
          onStarted={onStarted}
        />
      )}
    </>
  )
}

/** Move the picked files onto one drive: the drive and whether they fit
 * (the shared drive-and-free-space rule), what has to be downloaded first and
 * what can't move; the move itself then runs as a job in the status bar. */
/** What a move will do, in one sentence about the end result: how many files
 * end up on the drive, how much is written there, and any space it gives back.
 * How it gets there (copies kept for other records, records switched to a copy
 * already there) is civex's business. */
function moveSentence(plan: MovePlan, drive: string): string {
  if (nothingToDo(plan)) return `They are on ${drive} already.`
  const moving = plan.files + plan.repointed + plan.from_server
  const size = plan.bytes > 0 ? ` (${formatSize(plan.bytes)})` : ''
  const freed =
    plan.freed_bytes > 0
      ? `, and frees ${formatSize(plan.freed_bytes)} on other drives`
      : ''
  return `Moves ${plural(moving, 'file')}${size} onto ${drive}${freed}.`
}

/** Whether a move would change nothing: nothing to copy, download or point
 * elsewhere. */
function nothingToDo(plan: MovePlan): boolean {
  return plan.files === 0 && plan.from_server === 0 && plan.repointed === 0
}

const plural = (n: number, word: string) =>
  `${n.toLocaleString()} ${word}${n === 1 ? '' : 's'}`

export function MoveDialog({
  what,
  pick,
  onClose,
  onStarted,
}: {
  /** What is moved, as it is said: "12 files", "Encounter 7's files". */
  what: string
  pick: FilePick
  onClose: () => void
  /** Called once the move has started (it runs as a job in the status bar). */
  onStarted?: () => void
}) {
  const toast = useToast()
  const qc = useQueryClient()
  // Where the files are now (for the drive to suggest and what can't move).
  const { data: listing } = useFileListing({ ...pick, limit: 1 })
  const summary = listing?.summary ?? []
  // Suggest somewhere else: the drive the files are on (the place being
  // looked at, else the one holding most) is where they would move from.
  const from =
    pick.place ??
    [...summary]
      .filter((p) => p.kind === 'drive')
      .sort((a, b) => b.files - a.files)[0]?.place
  const { data: volumes = [] } = useVolumes()
  const elsewhere = volumes.find(
    (v) => v.available && v.state === 'online' && v.name !== from,
  )?.name
  const [chosen, setChosen] = useState<string | null>(null)
  const drive = useDriveChoice({
    holding: elsewhere,
    need: 0,
    allowProject: false,
    chosen,
  })
  // What it would do, asked of the server for the drive chosen: the same
  // rule the move itself follows.
  const { data: preview } = useQuery({
    queryKey: ['move-plan', pick, drive.target],
    queryFn: () => fileAccessApi.planMove(pick, drive.target),
    enabled: !!drive.target && drive.target !== PROJECT,
  })
  const plan = preview?.plan
  const stuck = summary.filter(
    (p) => p.kind === 'unreachable' || p.kind === 'missing',
  )
  return (
    <Modal onClose={onClose}>
      <ModalHeader onClose={onClose}>Move {what} to a drive</ModalHeader>
      <ModalBody className="space-y-3 text-sm">
        <DrivePicker
          label="Move them onto"
          value={drive.target}
          targets={drive.targets}
          allowProject={false}
          need={plan?.bytes ?? 0}
          free={drive.free}
          tooBig={drive.free != null && (plan?.bytes ?? 0) > drive.free}
          onChange={setChosen}
        />
        {plan && <p>{moveSentence(plan, drive.target)}</p>}
        {plan && plan.from_server > 0 && (
          <ToDownloadNotice toFetch={{ files: plan.from_server, bytes: 0 }} />
        )}
        {stuck.length > 0 && (
          <p className="text-attention">
            Left where they are:{' '}
            {stuck
              .map((p) => `${p.files} ${placeLabel(p).toLowerCase()}`)
              .join(', ')}
            .
          </p>
        )}
      </ModalBody>
      <ModalFooter>
        <Button variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button
          variant="primary"
          disabled={
            !drive.target ||
            drive.target === PROJECT ||
            !plan ||
            nothingToDo(plan)
          }
          onClick={() => {
            void moveFiles(
              { toast, qc, problem: () => undefined },
              pick,
              drive.target,
            )
            onStarted?.()
            onClose()
          }}
        >
          Move
        </Button>
      </ModalFooter>
    </Modal>
  )
}
