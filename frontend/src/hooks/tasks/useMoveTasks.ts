import type { Transfer } from '../../api/transfers'
import { HardDrive } from '../../components/ui/icons'
import { describeAmounts } from '../../utils/amounts'
import type { BackgroundTask, TaskAction } from '../../utils/backgroundTasks'
import {
  describeTransfer,
  filesHandled,
  isBusy,
  percentDone,
} from '../../utils/transfers'
import { usePauseTransfer, useTransfers } from '../useTransfers'

const DETAILS = '/settings/storage?tab=tasks'

/** File moves, as tasks: the running one with how far it is, how fast and how
 * long is left; one waiting for a drive to come back; or just how many are
 * waiting their turn. Nothing when no move is running, waiting, or waiting for
 * a drive. Everything else about moves is in Settings > Storage > Tasks. */
export function useMoveTasks(): BackgroundTask[] {
  const { data = [] } = useTransfers()
  const pause = usePauseTransfer()

  if (!data.some(isBusy)) return []
  const running = data.find((t) => t.status === 'running')
  const waitingForDrive = data.find(
    (t) => t.status === 'paused' && t.auto_resume,
  )
  const queued = data.filter((t) => t.status === 'queued').length
  const details: TaskAction = { label: 'Details', to: DETAILS }
  const more = queued > 0 ? `${queued} more waiting` : undefined

  if (running) {
    const p = running.progress
    const pct = percentDone(p)
    return [
      {
        id: 'moves',
        tone: 'info',
        icon: HardDrive,
        title: describeTransfer(running, true),
        progress: {
          fraction: pct / 100,
          label: 'Move progress',
          count: describeAmounts({
            done: filesHandled(p),
            total: p.files_total,
            unit: 'files',
            bytesDone: p.bytes_done,
            bytesTotal: p.bytes_total,
            rate: p.rate_bytes_per_second,
            eta: p.eta_seconds,
          }),
        },
        note: more,
        actions: [
          {
            label: running.control ? 'Pausing…' : 'Pause',
            disabled: pause.isPending || !!running.control,
            onClick: () => pause.mutate(running.id),
          },
          details,
        ],
      },
    ]
  }

  if (waitingForDrive)
    return [
      {
        id: 'moves',
        tone: 'attention',
        icon: HardDrive,
        title:
          `${describeTransfer(waitingForDrive, true)} is waiting` +
          (waitingForDrive.pause_reason
            ? `: ${waitingForDrive.pause_reason}`
            : ' for a drive to come back.') +
          ' It carries on by itself.',
        note: more,
        actions: [details],
      },
    ]

  return [
    {
      id: 'moves',
      tone: 'info',
      icon: HardDrive,
      title: `${queued} move${queued === 1 ? '' : 's'} waiting to start…`,
      actions: [details],
    },
  ]
}
