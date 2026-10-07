import { useSyncExternalStore } from 'react'

/** Something a person asked of their files that takes a while: working out what
 * is where, moving files onto one drive, building a folder. It lives outside
 * any component, so it carries on if they navigate away, and the status bar
 * (`useFileJobTasks`) shows it once it has been going for a moment. */
export interface FileJob {
  id: number
  title: string
  detail?: string
  /** How far along, when that is known (a move). */
  progress?: { fraction: number; label: string; count?: string }
  startedAt: number
  /** Only waiting on work that shows itself (a move has its own row in the
   * status bar): not shown twice. */
  waiting?: boolean
}

/** What the work being done can tell the bar as it goes. */
export interface JobHandle {
  update: (
    patch: Partial<Pick<FileJob, 'title' | 'detail' | 'progress' | 'waiting'>>,
  ) => void
}

let jobs: FileJob[] = []
let nextId = 1
const listeners = new Set<() => void>()

function publish(next: FileJob[]) {
  jobs = next
  listeners.forEach((l) => l())
}

const subscribe = (l: () => void) => {
  listeners.add(l)
  return () => {
    listeners.delete(l)
  }
}

/** Run `work` as a job: registered while it runs, removed when it ends (however
 * it ends), its result or error handed back to the caller. */
export async function runFileJob<T>(
  init: { title: string; detail?: string },
  work: (job: JobHandle) => Promise<T>,
): Promise<T> {
  const id = nextId++
  publish([...jobs, { id, ...init, startedAt: Date.now() }])
  try {
    return await work({
      update: (patch) =>
        publish(jobs.map((j) => (j.id === id ? { ...j, ...patch } : j))),
    })
  } finally {
    publish(jobs.filter((j) => j.id !== id))
  }
}

/** The jobs going on now. */
export function useFileJobs(): FileJob[] {
  return useSyncExternalStore(subscribe, () => jobs)
}
