import { api } from './client'

/** How this project stands with the authority it follows. */
export interface RemoteStatus {
  configured: boolean
  remote: string | null
  project_id: string
  /** The schedule is stopped; Sync now still works. */
  paused: boolean
  interval_seconds: number
  /** Which files this computer keeps a copy of: every file (downloaded in the
   * background), or only those opened or exported. */
  download_files: 'all' | 'opened'
  /** Files the records here cite that aren't on this computer yet. */
  files_to_fetch: number
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
  /** How far a long step has got while one runs on this server. */
  progress: SyncProgress | null
  /** A connect started here is still running (copying can take a while). */
  connecting: boolean
  /** Why the last connect started here failed. */
  connect_error: string | null
}

export interface SyncDevice {
  name: string
  /** Its key's short code. */
  fingerprint: string
  created_at: string
  last_seen_at: string | null
  revoked: boolean
}

export interface SyncInvite {
  /** The device it is for. */
  name: string
  created_at: string
  expires_at: string
}

export interface Authority {
  serving: boolean
  /** This authority's key's short code; null until it first invites. */
  fingerprint: string | null
  devices: SyncDevice[]
  /** Invites not used yet and not expired. */
  invites: SyncInvite[]
}

export interface SyncProgress {
  /** copying: from the authority; filling: an empty authority from here;
   * history: fetching what happened before this project joined. */
  phase: 'copying' | 'filling' | 'history' | string
  done: number
  total: number | null
  kind: string | null
  /** Downloading files: bytes so far, and how fast (bytes a second). */
  bytes_done?: number
  rate?: number
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
  'theirs' | 'mine' | 'value' | 'edited' | 'delete' | 'retry' | 'restore_above'

/** How a conflict ended: what a person chose, or what settled it by itself:
 * `sent` (a refused record went in once fixed), `replaced` (a later attempt
 * took its place). `retrying` is on an open one: sent again, no answer yet. */
export type ConflictResolution = ConflictTake | 'sent' | 'replaced' | 'retrying'

/** A value that did not go in as made. */
export interface SyncConflict {
  id: string
  /** not_taken: a change to the project's structure (or part of one action)
   * the server did not take; this copy was put back as the server has it. */
  kind:
    | 'conflict'
    | 'rejected'
    | 'edit_vs_delete'
    | 'not_taken'
    | 'not_applied'
    | string
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
  resolution: ConflictResolution | null
  /** What the value was before either side changed it. */
  base: unknown
  /** Who wrote the value that stayed, and when. */
  theirs_actor: string | null
  /** The device their change came through (verified by the server). */
  theirs_device?: string | null
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
  /** For a refused record that sits under deleted records here: those records,
   * topmost first. `restore_above` brings them back and sends it again. */
  sits_under?: { id: string; schema_name: string; name: string | null }[]
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

/** One collection's files on this computer. */
export interface CollectionFiles {
  id: string
  name: string
  /** In force: `keep` (a copy stays here) or `opened` (fetched when opened). */
  mode: 'keep' | 'opened'
  /** Set for this collection, rather than following the project's setting. */
  chosen: boolean
  files_here: number
  bytes_here: number
  /** Only on the server: on no drive here. */
  files_on_server: number
}

/** What freeing a collection's space removes (or would), and what it keeps. */
export interface FreeUp {
  files: number
  bytes: number
  /** Kept: also used by a collection kept on this computer. */
  kept_shared: number
  /** Kept: the server hasn't got them yet. */
  not_on_server: number
  done: boolean
}

export const remoteApi = {
  status: () => api.get<RemoteStatus>('/remote'),
  collectionFiles: () => api.get<CollectionFiles[]>('/remote/files'),
  setCollectionMode: (collection: string, mode: 'keep' | 'opened' | null) =>
    api.patch<CollectionFiles[]>(
      `/remote/files/${encodeURIComponent(collection)}`,
      { mode },
    ),
  freeUp: (collection: string, dryRun: boolean) =>
    api.post<FreeUp>(
      `/remote/files/${encodeURIComponent(collection)}/free-up?dry_run=${dryRun}`,
      {},
    ),
  /** This project as an authority: whether it accepts devices, and which. */
  authority: () => api.get<Authority>('/remote/authority'),
  setServing: (serving: boolean) =>
    api.patch<Authority>('/remote/authority', { serving }),
  /** The answer carries the invite: the only time it is shown. */
  invite: (name: string) =>
    api.post<Authority & { invite: string }>('/remote/authority/invites', {
      name,
    }),
  cancelInvite: (name: string) =>
    api.post<Authority>(
      `/remote/authority/invites/${encodeURIComponent(name)}/cancel`,
      {},
    ),
  revokeDevice: (name: string) =>
    api.post<Authority>(
      `/remote/authority/devices/${encodeURIComponent(name)}/revoke`,
      {},
    ),
  /** Starts connecting: the answer comes once the address and invite are
   * checked (this computer joins with the invite then); copying then runs in
   * the background (see `progress`). Without an invite, this computer must
   * have joined that address before. */
  connect: (url: string, invite?: string) =>
    api.post<{ mode: string }>('/remote/connect', { url, invite }),
  disconnect: () => api.post<RemoteStatus>('/remote/disconnect', {}),
  syncNow: () => api.post<{ requested: boolean }>('/remote/sync', {}),
  update: (body: {
    paused?: boolean
    interval_seconds?: number
    download_files?: 'all' | 'opened'
  }) => api.patch<RemoteStatus>('/remote', body),
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
