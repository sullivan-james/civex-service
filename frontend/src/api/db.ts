import { api } from './client'

export interface MigrationStatus {
  current_revision: string | null
  head_revision: string | null
  up_to_date: boolean
  error: string | null
}

export interface DockerStatus {
  name: string
  exists: boolean
  running: boolean
  volume_exists: boolean
}

export interface DbStatus {
  url: string
  dialect: string
  docker_managed: boolean
  migration: MigrationStatus
  docker: DockerStatus | null
}

export type MoveKind = 'sqlite' | 'docker' | 'postgres'

/** Where to move the project's data. Only the fields for `kind` are used. */
export interface MoveTarget {
  kind: MoveKind
  url?: string | null
  path?: string | null
  host?: string | null
  port?: number
  database?: string | null
  user?: string | null
  password?: string | null
}

export interface DatabaseSummary {
  label: string
  dialect: string
  location: string
  reachable: boolean
  error: string | null
  records: number
  rows: number
  size_bytes: number | null
}

export interface MovePreflight {
  source: DatabaseSummary
  target: DatabaseSummary
  target_label: string
  can_proceed: boolean
  problems: string[]
  warnings: string[]
  estimate_seconds: number
}

export interface MoveProgress {
  phase: 'copy' | 'verify' | 'finalize'
  table: string | null
  rows_done: number
  rows_total: number
  tables_done: number
  tables_total: number
  message: string
}

export type MoveStatus = 'running' | 'done' | 'failed' | 'cancelled'

export interface MoveRecord {
  id: string
  started_at: string
  finished_at: string | null
  status: MoveStatus
  source_label: string
  source_location: string
  target_label: string
  target_location: string
  seconds: number | null
  counts: Record<string, number>
  error: string | null
  problems: string[]
  reverted_at: string | null
}

export interface MoveJob {
  id: string
  status: MoveStatus
  progress: MoveProgress
  error: string | null
  record: MoveRecord | null
}

export const dbApi = {
  getSummary: () => api.get<DatabaseSummary>('/db/summary'),
  testConnection: (target: MoveTarget) =>
    api.post<{ ok: boolean; error: string | null }>(
      '/db/test-connection',
      target,
    ),
  preflightMove: (target: MoveTarget) =>
    api.post<MovePreflight>('/db/move/preflight', target),
  startMove: (target: MoveTarget) => api.post<MoveJob>('/db/move', target),
  getMove: (id: string) => api.get<MoveJob>(`/db/move/${id}`),
  cancelMove: (id: string) => api.post<MoveJob>(`/db/move/${id}/cancel`, {}),
  listMoves: () => api.get<MoveRecord[]>('/db/moves'),
  revertMove: (id: string) => api.post<DbStatus>(`/db/moves/${id}/revert`, {}),

  getStatus: () => api.get<DbStatus>('/db/status'),
  migrate: () => api.post<DbStatus>('/db/migrate', {}),
  setUrl: (url: string) => api.patch<DbStatus>('/db/config', { url }),
  setupDocker: () => api.post<DbStatus>('/db/docker/setup', {}),
  teardownDocker: () => api.post<DbStatus>('/db/docker/teardown', {}),
}
