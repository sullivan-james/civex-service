import type { BackgroundTask } from '../utils/backgroundTasks'
import { useAutomationTasks } from './tasks/useAutomationTasks'
import { useFileJobTasks } from './tasks/useFileJobTasks'
import { useMoveTasks } from './tasks/useMoveTasks'
import { useSyncTasks } from './tasks/useSyncTasks'

/** Everything going on in the background, from every source, as one list for the
 * status bar. To show another kind of work, write a source hook that returns its
 * `BackgroundTask`s and add one line here (they are called one by one, not in a
 * loop, so React sees the same hooks in the same order every render). */
export function useBackgroundTasks(): BackgroundTask[] {
  return [
    ...useFileJobTasks(),
    ...useMoveTasks(),
    ...useSyncTasks(),
    ...useAutomationTasks(),
  ]
}
