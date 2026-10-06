import { useEffect, useState } from 'react'
import { FolderOpen } from '../../components/ui/icons'
import type { BackgroundTask } from '../../utils/backgroundTasks'
import { useFileJobs } from '../fileJobs'

/** How long a job must have been going before it shows in the bar: most are over
 * in a moment, and must not flash. */
export const FILE_JOB_SHOW_AFTER_MS = 1000

/** Things being done to files, as tasks: "Preparing files…", "Moving 120 files
 * to archive…", "Building the folder…", each shown once it has been going for
 * a second. */
export function useFileJobTasks(): BackgroundTask[] {
  const jobs = useFileJobs()
  const [now, setNow] = useState(() => Date.now())

  // Wake up when the next job comes due, so it appears without anything else
  // having to change.
  useEffect(() => {
    const waiting = jobs
      .map((j) => j.startedAt + FILE_JOB_SHOW_AFTER_MS - Date.now())
      .filter((ms) => ms > 0)
    if (waiting.length === 0) return
    const timer = setTimeout(() => setNow(Date.now()), Math.min(...waiting))
    return () => clearTimeout(timer)
  }, [jobs])

  return jobs
    .filter((j) => now - j.startedAt >= FILE_JOB_SHOW_AFTER_MS)
    .map((j) => ({
      id: `file-job-${j.id}`,
      tone: 'info' as const,
      icon: FolderOpen,
      spinning: true,
      title: j.title,
      detail: j.detail,
      progress: j.progress,
    }))
}
