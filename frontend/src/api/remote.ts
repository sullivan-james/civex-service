import { api } from './client'

/** How this project stands with the authority it follows. */
export interface RemoteStatus {
  configured: boolean
  remote: string | null
  project_id: string
  /** The schedule is stopped; Sync now still works. */
  paused: boolean
  interval_seconds: number
  /** This project is itself an authority. */
  serving: boolean
  /** Changes made here that have not been sent. */
  pending: number
  open_conflicts: number
  last_synced_at: string | null
  last_error: string | null
  last_error_at: string | null
  running: boolean
  /** What the last sync run by this server did (null until one has run). */
  last_result: SyncResult | null
}

export interface SyncResult {
  pulled: number
  pushed: number
  files_sent: number
  conflicts: number
  rejected: number
}

/** How a conflict is settled. Which of these a row offers is the server's word
 * (`takes`), so this screen keeps no rule of its own. */
export type ConflictTake =
  'theirs' | 'mine' | 'value' | 'edited' | 'delete' | 'retry'

/** A value that did not go in as made. */
export interface SyncConflict {
  id: string
  kind: 'conflict' | 'rejected' | 'edit_vs_delete' | 'not_applied' | string
  entity_type: string
  entity_id: string
  field: string | null
  /** What this device set. */
  yours: unknown
  /** What the authority kept. */
  theirs: unknown
  device_name: string | null
  message: string | null
  status: 'open' | 'resolved'
  created_at: string
  resolved_at: string | null
  resolution: ConflictTake | null
  /** What the value was before either side changed it. */
  base: unknown
  /** Who wrote the value that stayed, and when. */
  theirs_actor: string | null
  theirs_at: string | null
  /** Worked out when read (records only): what a person recognises. */
  record_name: string | null
  dataset_name: string | null
  schema_name: string | null
  field_label: string | null
  dtype: string | null
  /** The value on the record now. */
  current: unknown
  /** The record's value is no longer the one that stayed: it changed again. */
  stale: boolean
  record_deleted: boolean
  takes: ConflictTake[]
  /** Other values the same edit set that did go in. */
  also_saved: { field_label: string; value: unknown }[]
  /** For a refused change, or an edit that met a delete: what was tried. */
  attempted: 'create' | 'update' | 'delete' | null
  /** ...and the fields it set, to show on the record itself. */
  changes: ConflictChange[]
}

/** One field a refused or colliding change set. */
export interface ConflictChange {
  field_id: string
  field_name: string
  field_label: string
  dtype: string | null
  before: unknown
  after: unknown
  /** The value on the record now. */
  current: unknown
}

export interface ResolveBody {
  take: ConflictTake
  /** The value, for `take: 'value'`. */
  value?: unknown
  /** Put it back even though the record's value changed since. */
  force?: boolean
}

/** Which open conflicts a bulk action covers: the ones given, or every one that
 * matches (nothing given = all of them, not only those on screen). */
export interface ResolveManyBody {
  take: Exclude<ConflictTake, 'value' | 'edited'>
  ids?: string[]
  kind?: string
  record_id?: string
  /** Count what would be settled; change nothing. */
  dry_run?: boolean
}

export interface ResolveManyResult {
  done: number
  settled_ids: string[]
  /** Left open: they don't offer that way of settling. */
  not_offered: number
  /** Left open: failed their checks (for example, changed again since). */
  failed: { id: string; message: string }[]
}

export const remoteApi = {
  status: () => api.get<RemoteStatus>('/remote'),
  connect: (url: string, token: string) =>
    api.post<{ mode: string }>('/remote/connect', { url, token }),
  disconnect: () => api.post<RemoteStatus>('/remote/disconnect', {}),
  syncNow: () => api.post<{ requested: boolean }>('/remote/sync', {}),
  update: (body: { paused?: boolean; interval_seconds?: number }) =>
    api.patch<RemoteStatus>('/remote', body),
  conflicts: (status: 'open' | 'resolved' | 'all' = 'open', record?: string) =>
    api.get<SyncConflict[]>(
      `/remote/conflicts?status=${status}${record ? `&record=${record}` : ''}`,
    ),
  resolve: (id: string, body: ResolveBody) =>
    api.post<RemoteStatus>(`/remote/conflicts/${id}/resolve`, body),
  resolveMany: (body: ResolveManyBody) =>
    api.post<ResolveManyResult>('/remote/conflicts/resolve-many', body),
  /** Take back conflicts settled with `theirs`. */
  reopen: (ids: string[]) =>
    api.post<{ reopened: number }>('/remote/conflicts/reopen', { ids }),
}
