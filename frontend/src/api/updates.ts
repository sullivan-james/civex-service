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
  last: UpdateAttempt | null
}

export const updatesApi = {
  status: (pre: boolean) =>
    api.get<UpdateStatus>(`/update?pre=${pre ? 'true' : 'false'}`),
  /** civex closes once this answers, updates, and starts again. */
  start: (pre: boolean) =>
    api.post<{ restarting: boolean }>('/update', { pre }),
}
