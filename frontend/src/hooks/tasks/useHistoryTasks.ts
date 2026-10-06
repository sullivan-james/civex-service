import { History } from '../../components/ui/icons'
import type { BackgroundTask } from '../../utils/backgroundTasks'
import { useHistoryStorage } from '../useAudit'

/** Converting history written before this version to what-changed form, as a
 * task: shown only while it runs, with how far it has got. It needs nobody;
 * the project is usable throughout. */
export function useHistoryTasks(): BackgroundTask[] {
  const { data } = useHistoryStorage()
  if (!data?.converting || !data.total) return []
  const done = data.done ?? 0
  return [
    {
      id: 'history-compaction',
      tone: 'info',
      icon: History,
      spinning: true,
      title: 'Tidying history',
      progress: {
        fraction: done / data.total,
        label: 'History converted',
      },
      detail: `${done.toLocaleString()} of ${data.total.toLocaleString()} changes`,
      actions: [{ label: 'Details', to: '/settings/database' }],
    },
  ]
}
