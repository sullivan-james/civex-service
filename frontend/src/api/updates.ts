import { api } from './client'

/** The outcome of the last update started from the app. */
export interface UpdateAttempt {
  at: string
  from_version: string
  to_version: string | null
  ok: boolean
  /** What went wrong; blank when it worked. */
  message: string
}

/** Whether a newer civex is available, and whether this copy can install it
 * from the app (`GET /update`). */
export interface UpdateStatus {
  current: string
  /** Null when PyPI couldn't be reached (`error` says why). */
  latest: string | null
  newer: boolean
  pre: boolean
  installer: string
  can_update: boolean
  /** Why it can't, in plain words; blank when it can. */
  blocked: string
  error: string
  /** The last update's outcome while it is news; null once civex has moved
   * on or it was dismissed. */
  last: UpdateAttempt | null
  /** Other servers running from this copy: updating stops them and starts
   * them again afterwards. */
  running: string[]
}

export interface StartUpdate {
  pre: boolean
  /** The version to install: the one the status showed. */
  version?: string | null
  /** Stop the other servers running from this copy (and start them again). */
  stopOthers?: boolean
}

export const updatesApi = {
  status: (pre: boolean) =>
    api.get<UpdateStatus>(`/update?pre=${pre ? 'true' : 'false'}`),
  /** civex closes once this answers, updates, and starts again. */
  start: ({ pre, version, stopOthers }: StartUpdate) =>
    api.post<{ restarting: boolean }>('/update', {
      pre,
      version: version ?? null,
      stop_others: !!stopOthers,
    }),
  /** Forget the last update's outcome: it was seen. */
  dismissLast: () => api.delete<void>('/update/last'),
}
