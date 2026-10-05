import { RefreshCw } from '../../components/ui/icons'
import type { BackgroundTask } from '../../utils/backgroundTasks'
import { useRemoteStatus, useSyncNow } from '../useRemote'

const DETAILS = '/settings/sync'

/** Syncing, as a task: shown while a sync is running, when the last attempt
 * failed (it tries again by itself), or when values are waiting for a person to
 * choose. Nothing when all is well, so a quiet project has a quiet bar. */
export function useSyncTasks(): BackgroundTask[] {
  const { data } = useRemoteStatus()
  const syncNow = useSyncNow()
  if (!data?.configured) return []
  const details = { label: 'Details', to: DETAILS }

  if (data.running)
    return [
      {
        id: 'sync',
        tone: 'info',
        icon: RefreshCw,
        spinning: true,
        title: 'Syncing…',
        detail:
          data.pending > 0 ? `${data.pending} change(s) to send` : undefined,
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
        note:
          data.pending > 0
            ? `${data.pending} change(s) saved here, not yet sent`
            : undefined,
        actions: [
          {
            label: 'Try now',
            disabled: syncNow.isPending,
            onClick: () => syncNow.mutate(),
          },
          details,
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
        actions: [{ label: 'Review', to: DETAILS }],
      },
    ]

  return []
}
