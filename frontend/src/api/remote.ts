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
  resolution: 'mine' | 'theirs' | null
}

export const remoteApi = {
  status: () => api.get<RemoteStatus>('/remote'),
  connect: (url: string, token: string) =>
    api.post<{ mode: string }>('/remote/connect', { url, token }),
  disconnect: () => api.post<RemoteStatus>('/remote/disconnect', {}),
  syncNow: () => api.post<{ requested: boolean }>('/remote/sync', {}),
  update: (body: { paused?: boolean; interval_seconds?: number }) =>
    api.patch<RemoteStatus>('/remote', body),
  conflicts: (status: 'open' | 'resolved' | 'all' = 'open') =>
    api.get<SyncConflict[]>(`/remote/conflicts?status=${status}`),
  resolve: (id: string, take: 'mine' | 'theirs') =>
    api.post<RemoteStatus>(`/remote/conflicts/${id}/resolve`, { take }),
}
