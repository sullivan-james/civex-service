import { Database } from '../../components/ui/icons'
import type { BackgroundTask } from '../../utils/backgroundTasks'
import { useHasFeature } from '../useFeatures'
import { useIndexReport } from '../useFieldIndex'

/** Field indexes being built in the background, as a task: shown only while
 * one is under way, with how far it has got. Nothing waits on it: lists work
 * meanwhile, only slower. */
export function useIndexTasks(): BackgroundTask[] {
  const has = useHasFeature()
  const offered = has('db_admin')
  const { data } = useIndexReport(offered)
  if (!offered || !data) return []
  const p = data.progress
  if (p && p.total > 0 && p.field_label) {
    const count = `${Math.min(p.done + 1, p.total)} of ${p.total}`
    return [
      {
        id: 'field-indexes',
        tone: 'info',
        icon: Database,
        spinning: !p.waiting,
        title: `Speeding up sorting on ${p.schema_label}`,
        progress: { fraction: p.done / p.total, label: 'Indexes built', count },
        detail: p.waiting
          ? 'Waiting for a moment when nobody is saving'
          : `Indexing ${p.field_label}`,
        actions: [{ label: 'Details', to: '/settings/database' }],
      },
    ]
  }
  if (data.elsewhere) {
    return [
      {
        id: 'field-indexes',
        tone: 'info',
        icon: Database,
        spinning: true,
        title: 'Speeding up sorting',
        detail: 'Another civex process is building indexes',
      },
    ]
  }
  return []
}
