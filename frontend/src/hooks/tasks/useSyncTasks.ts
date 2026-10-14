import { logHref } from '../../api/logs'
import { RefreshCw } from '../../components/ui/icons'
import type { BackgroundTask } from '../../utils/backgroundTasks'
import { useRemoteStatus, useSyncNow } from '../useRemote'
import { describeSyncProgress } from '../../utils/syncProgress'

const DETAILS = '/settings/sync'
const REVIEW = '/sync/review'

/** Syncing, as a task: shown while a sync is running (with a bar while the
 * project is copied or its history arrives), when the last attempt failed (it
 * tries again by itself), or when values are waiting for a person to choose.
 * Nothing when all is well, so a quiet project has a quiet bar. Files are
 * not syncing: they move apart and are their own task (`useServerFilesTasks`). */
export function useSyncTasks(): BackgroundTask[] {
  const { data } = useRemoteStatus()
  const syncNow = useSyncNow()
  if (!data || (!data.configured && !data.connecting)) return []
  const details = { label: 'Details', to: DETAILS }
  // What the server wrote about it, warnings and errors only.
  const viewLog = { label: 'View log', to: logHref('project', 'warning') }

  if (data.progress) {
    const text = describeSyncProgress(data.progress)
    return [
      {
        id: 'sync',
        tone: 'info',
        icon: RefreshCw,
        spinning: true,
        title: text.title,
        progress:
          text.fraction != null
            ? { fraction: text.fraction, label: text.title, count: text.count }
            : undefined,
        // Without a bar (how many isn't known yet), the count says how far.
        detail: text.fraction != null ? undefined : text.detail,
        actions: [details],
      },
    ]
  }

  if (data.connecting)
    return [
      {
        id: 'sync',
        tone: 'info',
        icon: RefreshCw,
        spinning: true,
        title: 'Connecting to the server…',
        actions: [details],
      },
    ]

  if (data.connect_error)
    return [
      {
        id: 'sync',
        tone: 'attention',
        icon: RefreshCw,
        title: 'Could not connect',
        detail: data.connect_error,
        actions: [details, viewLog],
      },
    ]

  if (data.running)
    return [
      {
        id: 'sync',
        tone: 'info',
        icon: RefreshCw,
        spinning: true,
        title: 'Syncing…',
        detail: toSend(data.pending),
        actions: [details],
      },
    ]

  if (data.last_error)
    return [
      {
        id: 'sync',
        tone: 'attention',
        icon: RefreshCw,
        title: 'Could not sync',
        detail: data.last_error,
        note: notSent(data.pending),
        actions: [
          {
            label: 'Try now',
            disabled: syncNow.isPending,
            onClick: () => syncNow.mutate(),
          },
          details,
          viewLog,
        ],
      },
    ]

  if (data.open_conflicts > 0)
    return [
      {
        id: 'sync',
        tone: 'attention',
        icon: RefreshCw,
        title: `${data.open_conflicts} change${
          data.open_conflicts === 1 ? ' was' : 's were'
        } not taken as made`,
        actions: [{ label: 'Review', to: REVIEW }],
      },
    ]

  return []
}

function plural(n: number, what: string): string {
  return `${n.toLocaleString()} ${what}${n === 1 ? '' : 's'}`
}

/** What is still to go up, while a sync runs. */
function toSend(changes: number): string | undefined {
  return changes > 0 ? `${plural(changes, 'change')} to send` : undefined
}

/** What is saved here but not on the server, when syncing failed. */
function notSent(changes: number): string | undefined {
  return changes > 0
    ? `${plural(changes, 'change')} saved here, not yet sent`
    : undefined
}
