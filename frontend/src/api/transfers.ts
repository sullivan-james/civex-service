import { api } from './client'

export interface TransferSpec {
  kind: 'drain' | 'consolidate' | 'files'
  targets: string[]
  sources: string[]
  collection_ids: string[]
  /** files: the content moved, by hash. */
  shas?: string[]
  verify: 'copy' | 'full'
  freeze_sources: boolean
}

export interface TransferPlan {
  files: number
  bytes: number
  already_there: number
  /** Of `files`, those copied, not moved: their drive is the home of another
   * collection that uses them, and keeps its copy. */
  copied: number
  copied_bytes: number
  targets: {
    volume: string
    files: number
    bytes: number
    free_bytes: number | null
  }[]
  problems: string[]
  warnings: string[]
  can_proceed: boolean
}

export interface TransferProgress {
  files_total: number
  files_done: number
  files_skipped: number
  files_failed: number
  bytes_total: number
  bytes_done: number
  current: string | null
  current_bytes: number
  current_total: number
  rate_bytes_per_second: number
  eta_seconds: number | null
  message: string
}

export type TransferStatus =
  | 'queued'
  | 'running'
  | 'paused'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'interrupted'

export interface Transfer {
  id: string
  kind: 'drain' | 'consolidate' | 'files'
  status: TransferStatus
  spec: TransferSpec
  plan: TransferPlan | null
  progress: TransferProgress
  failures: { sha256: string; volume: string; reason: string }[]
  failures_total: number
  pause_reason: string | null
  auto_resume: boolean
  error: string | null
  control: string | null
  frozen: Record<string, string>
  live: boolean
  created_at: string | null
  started_at: string | null
  finished_at: string | null
  updated_at: string | null
}

const base = '/store/transfers'

export const transfersApi = {
  list: () => api.get<Transfer[]>(base),
  get: (id: string) => api.get<Transfer>(`${base}/${id}`),
  preview: (spec: TransferSpec) =>
    api.post<TransferPlan>(`${base}/preview`, spec),
  start: (spec: TransferSpec) => api.post<Transfer>(base, spec),
  pause: (id: string) => api.post<Transfer>(`${base}/${id}/pause`, {}),
  resume: (id: string) => api.post<Transfer>(`${base}/${id}/resume`, {}),
  cancel: (id: string) => api.post<Transfer>(`${base}/${id}/cancel`, {}),
}
