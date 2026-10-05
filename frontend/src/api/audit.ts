import { api } from './client'
import type { FilterTreeWire } from '../utils/filterTree'
import type { Blocker } from './restore'
import type { RunFilterField } from './workflows'

/** One field (or, for a schema, collection or view, one attribute) an entry
 * changed. `before` / `after` are null when unset on that side, so a create
 * has only afters and a delete only befores. */
export interface AuditChange {
  field: string
  /** The field's display name now; null when it has since been renamed or
   * deleted, and for entries that aren't about a record. */
  label: string | null
  dtype: string | null
  before: unknown
  after: unknown
  /** Set when this field has since been deleted: `deleted` can still be
   * restored (on `schema_name`), `gone` was deleted for good. */
  deleted?: {
    status: 'deleted' | 'gone'
    id: string
    schema_name?: string
    deleted_at?: string | null
  } | null
}

export interface AuditNow {
  kind: 'record' | 'collection' | 'schema' | 'field'
  /** What to restore or purge it by: a record's or field's id, else its name. */
  ref: string | null
  /** live: it exists; deleted: in Recently Deleted, restorable; gone: purged. */
  status: 'live' | 'deleted' | 'gone'
  name: string | null
  /** Known even for a record that is gone for good; for a field, the schema
   * it belongs to. */
  schema_name: string | null
  collection: string | null
  deleted_at: string | null
}

export interface AuditLogEntry {
  id: string
  /** Who made the change, as the machine that made it reported it (the OS
   * user). Not verified. Null for entries from before it was recorded. */
  actor?: string | null
  action: string
  entity_type: string
  entity_id: string
  /** Full entity snapshot before the change. Null on create. */
  old_data: Record<string, unknown> | null
  /** Full entity snapshot after the change. Null on delete. */
  new_data: Record<string, unknown> | null
  /** What the entry changed, worked out by the server, in schema order. */
  changes: AuditChange[]
  /** Where the record this is about is now, so a lost one can be told from
   * one that was edited, deleted or purged. Null for anything but a record. */
  now: AuditNow | null
  timestamp: string
}

export interface PaginatedAuditLog {
  items: AuditLogEntry[]
  total: number
  offset: number
  limit: number
}

/** What a history table can ask for: one kind of action, and an order
 * (`timestamp` or `action`, then `:asc` / `:desc`). */
export interface AuditView {
  action?: string
  sort?: string
}

/** `<base>/audit` with paging and the view, for every entity's history. */
export function auditUrl(
  base: string,
  offset: number,
  limit: number,
  view?: AuditView,
): string {
  const qs = new URLSearchParams({
    offset: String(offset),
    limit: String(limit),
  })
  if (view?.action) qs.set('action', view.action)
  if (view?.sort) qs.set('sort', view.sort)
  return `${base}/audit?${qs}`
}

/** apply: still as the entry left it; conflict: edited since (put back only
 * when forced); same: already the older value; skipped: can't be put back. */
export type RevertStatus = 'apply' | 'conflict' | 'same' | 'skipped'

export interface RevertField {
  field: string
  label: string | null
  dtype: string | null
  current: unknown
  target: unknown
  status: RevertStatus
  reason: string | null
}

export interface RevertPlan {
  audit_id: string
  entity_type: string
  entity_id: string
  /** update puts fields back, restore undoes a delete, delete undoes a create. */
  kind: 'update' | 'restore' | 'delete' | null
  fields: RevertField[]
  /** Why nothing can be undone at all. */
  blocked: string | null
  /** When a deleted record can't come back yet, what to restore first. */
  blocker: Blocker | null
  can_apply: boolean
  has_conflicts: boolean
}

export interface RevertResult {
  audit_id: string
  entity_id: string
  kind: string
  applied: string[]
}

export const auditApi = {
  /** The fields a history filter may test, with their types and operators. */
  filterFields: () => api.get<RunFilterField[]>('/audit/filter-fields'),

  /** The project's history as events: a batch is one, however much it holds. */
  events: (query: AuditEventQuery, offset = 0, limit = 25) =>
    api.get<PaginatedAuditEvents>(eventsUrl(query, offset, limit)),

  /** The changes in one batch. */
  batchEntries: (id: string, offset = 0, limit = 25) =>
    api.get<PaginatedAuditLog>(
      `/audit/batches/${id}/entries?offset=${offset}&limit=${limit}`,
    ),

  /** What restoring every deleted thing the filter matches would do. */
  restoreAllPlan: (query: AuditEventQuery) => {
    const qs = new URLSearchParams()
    if (query.filter) qs.set('filter', JSON.stringify(query.filter))
    if (query.search) qs.set('q', query.search)
    if (query.batch) qs.set('batch', query.batch)
    return api.get<RestoreAllPlan>(`/audit/restore-all?${qs}`)
  },

  /** Restore every deleted thing the filter matches, as one event in history. */
  restoreAll: (query: AuditEventQuery) =>
    api.post<RestoreAllResult>('/audit/restore-all', {
      filter: query.filter ?? null,
      q: query.search ?? null,
      batch: query.batch ?? null,
    }),

  /** Start a batch for work done over many requests, such as an import; send
   * its id as `X-Civex-Batch` on each of them. */
  openBatch: (label: string) =>
    api.post<AuditBatch>('/audit/batches', { kind: 'import', label }),

  /** What undoing the entry would do, without doing it. */
  revertPlan: (id: string) => api.get<RevertPlan>(`/audit/${id}/revert`),

  /** Undo the entry. Fields edited since are left alone unless `force`. */
  revert: (id: string, options: { fields?: string[]; force?: boolean } = {}) =>
    api.post<RevertResult>(`/audit/${id}/revert`, options),
}

/** What restoring everything deleted that a filter matches would do. */
export interface RestoreAllPlan {
  collections: number
  schemas: number
  fields: number
  records: number
  things: number
  /** Records that would be live afterwards, counting what came back with each. */
  restores: number
  /** Matched, but under something deleted that is not in the set. */
  blocked: number
  truncated: boolean
}

export interface RestoreAllResult {
  restored: number
  records: number
  blocked: number
}

/** What a bulk operation was: an import, a delete that took a tree with it, a
 * workflow run. */
export interface AuditBatch {
  id: string
  kind: 'import' | 'delete' | 'restore' | 'purge' | 'workflow'
  /** A workflow's name, or the file imported. */
  label: string | null
  /** What started it: a workflow run's id. */
  ref: string | null
  created_at: string
}

/** What a batch holds, by kind of thing and action. */
export interface AuditPart {
  entity_type: string
  action: string
  count: number
}

/** One line of history: a single change, or a whole batch of them. */
export interface AuditEvent {
  id: string
  kind: 'entry' | 'batch'
  timestamp: string
  /** Changes in it that match the filters. */
  count: number
  entry: AuditLogEntry | null
  batch: AuditBatch | null
  parts: AuditPart[]
  /** Who made it (the OS user on the machine that did); for a batch, who made
   * its changes. Null when it was not recorded. */
  actor?: string | null
}

export interface PaginatedAuditEvents {
  items: AuditEvent[]
  total: number
  offset: number
  limit: number
}

/** What the whole-project history can be asked for: the filter tree (over the
 * fields from `filterFields`), a text search and an order. */
export interface AuditEventQuery {
  filter?: FilterTreeWire | null
  search?: string
  sort?: string
  /** Only for restoring: just what this one bulk delete took. */
  batch?: string
}

export function eventsUrl(
  query: AuditEventQuery,
  offset: number,
  limit: number,
) {
  const qs = new URLSearchParams({
    offset: String(offset),
    limit: String(limit),
  })
  if (query.filter) qs.set('filter', JSON.stringify(query.filter))
  if (query.search) qs.set('q', query.search)
  if (query.sort) qs.set('sort', query.sort)
  return `/audit/events?${qs}`
}
