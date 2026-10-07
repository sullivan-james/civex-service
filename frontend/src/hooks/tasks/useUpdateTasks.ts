import { Sparkles } from '../../components/ui/icons'
import type { BackgroundTask } from '../../utils/backgroundTasks'
import {
  clearRestartProblem,
  restartForUpdate,
  useRestartPhase,
} from '../../utils/updateRestart'
import {
  usePreReleases,
  useUpdatePref,
  useUpdateStatus,
  writeUpdatePref,
} from '../useUpdate'

const DETAILS = '/settings/updates'

/** Updating civex itself, as tasks: while it restarts to update; a newer
 * version this copy can install (until put off with Later, for that version);
 * and an update that didn't work, once. Quiet otherwise. */
export function useUpdateTasks(): BackgroundTask[] {
  const [pre] = usePreReleases()
  const { data } = useUpdateStatus(pre)
  const phase = useRestartPhase()
  const later = useUpdatePref('later')
  const seen = useUpdatePref('seen')

  if (phase.kind === 'closing' || phase.kind === 'restarting')
    return [
      {
        id: 'update',
        tone: 'info',
        icon: Sparkles,
        spinning: true,
        title: 'Updating civex',
        detail:
          phase.kind === 'closing'
            ? 'Closing to update…'
            : 'This page reloads when civex is back.',
      },
    ]
  if (phase.kind === 'failed' || phase.kind === 'timeout')
    return [
      {
        id: 'update',
        tone: 'attention',
        icon: Sparkles,
        title:
          phase.kind === 'failed'
            ? 'civex couldn’t start the update'
            : 'civex hasn’t come back from updating',
        detail: phase.kind === 'failed' ? phase.message : undefined,
        actions: [
          { label: 'Details', to: DETAILS },
          { label: 'Dismiss', onClick: clearRestartProblem },
        ],
      },
    ]

  const tasks: BackgroundTask[] = []
  if (data?.last && !data.last.ok && seen !== data.last.at)
    tasks.push({
      id: 'update-result',
      tone: 'attention',
      icon: Sparkles,
      title: 'civex didn’t update',
      detail: data.last.message,
      actions: [
        { label: 'Details', to: DETAILS },
        {
          label: 'Dismiss',
          onClick: () => writeUpdatePref('seen', data.last?.at ?? null),
        },
      ],
    })
  if (data?.newer && data.can_update && data.latest && later !== data.latest)
    tasks.push({
      id: 'update-available',
      tone: 'info',
      icon: Sparkles,
      title: `civex ${data.latest} is available`,
      note: `You have ${data.current}`,
      actions: [
        {
          label: 'Update and restart',
          variant: 'primary',
          onClick: () => void restartForUpdate(pre),
        },
        { label: 'Details', to: DETAILS },
        {
          label: 'Later',
          onClick: () => writeUpdatePref('later', data.latest),
        },
      ],
    })
  return tasks
}
