import { api } from './client'

/** What to clean up: the settings, and/or a date per kind (which wins over the
 * setting for its kind). Dates are ISO instants. */
export interface RetentionRequest {
  from_settings?: boolean
  deleted_before?: string | null
  audit_before?: string | null
  runs_before?: string | null
}

/** What a clean-up removed, or with `dry_run` would remove. */
export interface RetentionReport {
  dry_run: boolean
  deleted_records: number
  deleted_collections: number
  deleted_schemas: number
  /** Deleted things that could not be removed, with why. */
  skipped: string[]
  audit_entries: number
  audit_batches: number
  /** Older history kept: it is about something that can still be restored. */
  audit_kept_restorable: number
  /** Older history kept: it has not been pushed to the remote. */
  audit_kept_unsynced: number
  runs: number
  run_steps: number
  anything: boolean
}

/** History entries about records that no longer exist. */
export interface PurgedHistory {
  dry_run: boolean
  entries: number
}

export const retentionApi = {
  /** Count (`dryRun`) or delete the history of records that were permanently
   * deleted before that removed it. Each is left one tombstone. */
  purgedHistory: (dryRun: boolean) =>
    api.post<PurgedHistory>('/retention/purged-history', { dry_run: dryRun }),

  /** Count (`dry_run`) or remove what the request covers. */
  run: (request: RetentionRequest, dryRun: boolean) =>
    api.post<RetentionReport>('/retention/run', {
      ...request,
      dry_run: dryRun,
    }),
}
