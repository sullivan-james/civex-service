import { api } from './client'
import { auditUrl, type AuditView, type PaginatedAuditLog } from './audit'
import {
  recordQueryString,
  type PageParams,
  type RecordQueryParams,
} from './query'

export interface CivexRecord {
  id: string
  dataset_id: string
  schema_name: string
  parent_record_id: string | null
  data: Record<string, unknown>
  natural_name: string | null
  created_at: string
  updated_at: string
  /** When this record was soft-deleted. Null means live. */
  deleted_at: string | null
  /** id -> that target's natural_name, for every reference/reference_list
   * value on this record. Null target label means the target has no
   * natural_name (not that it's missing). */
  reference_labels: Record<string, string | null> | null
  /** Name of the collection this record lives in. */
  collection?: string | null
  /** Reference targets that live in a different (global) collection:
   * target id -> that collection's name. Own-collection targets are absent. */
  reference_collections?: Record<string, string> | null
  /** Only when requested: live child count per child schema name. */
  child_counts?: Record<string, number> | null
  /** Only when `columns` were requested: the columns this record's own
   * `data` can't answer (inherited fields, `ref.field` joins). */
  derived?: Record<string, unknown> | null
  /** Only on a single-record fetch: the parent chain, root first. */
  ancestors?: RecordRef[] | null
  /** Only on a single-record fetch of a live record: the deleted records
   * directly above it, topmost first. Not empty means it is out of sight:
   * nothing above it lists it, and a sync server refuses it. */
  deleted_above?: RecordRef[] | null
  /** Values this record still holds for fields deleted from its schema. They
   * come back in `data` when the field is restored. */
  deleted_fields?: DeletedFieldValue[] | null
}

export interface RestoreSelectedResult {
  /** Chosen records that came back. */
  restored: number
  /** Records live again in all, counting the parents brought back. */
  came_back: number
  /** Chosen records that stayed deleted. */
  left: number
}

export interface DeletedFieldValue {
  id: string
  name: string
  label: string
  dtype: string
  /** The schema it was defined on: where to restore it. */
  schema_name: string
  deleted_at: string | null
  value: unknown
}

export interface RecordRef {
  id: string
  schema_name: string
  natural_name: string | null
}

/** A live record that sits under a deleted one, and what it sits under. */
export interface Orphan {
  record: RecordRef
  collection: string | null
  above: RecordRef[]
}

/** One row of a record's "Referenced by": how many live records of one
 * schema, in one collection, point at it through one reference field. */
export interface ReferrerGroup {
  dataset_id: string
  collection: string
  /** The referring records' schema, which owns the field. */
  schema_name: string
  field_name: string
  dtype: 'reference' | 'reference_list'
  count: number
}

export interface PaginatedRecords {
  items: CivexRecord[]
  total: number
  offset: number
  limit: number
}

export type ListParams = RecordQueryParams & PageParams

/** A record's name as it is now, with what is needed to say what it is. */
export interface RecordLabel {
  id: string
  schema_name: string
  /** Null when nothing in the record can name it. */
  natural_name: string | null
  /** In Recently Deleted: it still has a name, and can be restored. */
  deleted: boolean
  /** When it was deleted; null for a live record. */
  deleted_at?: string | null
}

/** The header that puts a request's changes in a batch (see `auditApi.openBatch`). */
function batchHeaders(batchId?: string): Record<string, string> | undefined {
  return batchId
    ? { 'Content-Type': 'application/json', 'X-Civex-Batch': batchId }
    : undefined
}

export const recordsApi = {
  /** Names for any number of ids in one request. Ids that aren't records, or
   * whose record is gone, are not in the answer. */
  labels: (ids: string[]) =>
    api.post<RecordLabel[]>('/records/labels', { ids }),

  list: (datasetName: string, params?: ListParams) =>
    api.get<PaginatedRecords>(
      `/collections/${encodeURIComponent(datasetName)}/records${recordQueryString(params)}`,
    ),

  /** A schema's records across every collection -- what a saved view browses. */
  listBySchema: (schemaName: string, params?: ListParams) =>
    api.get<PaginatedRecords>(
      `/schemas/${encodeURIComponent(schemaName)}/records${recordQueryString(params)}`,
    ),

  /** Matching records per schema name (`within` scopes it to one record's
   * descendants). */
  counts: (datasetName: string, params?: RecordQueryParams) =>
    api.get<Record<string, number>>(
      `/collections/${encodeURIComponent(datasetName)}/record-counts${recordQueryString(params)}`,
    ),

  get: (id: string) => api.get<CivexRecord>(`/records/${id}`),

  /** What references this record, counted per collection/schema/field. */
  referrers: (id: string) =>
    api.get<ReferrerGroup[]>(`/records/${id}/referrers`),

  /** `batchId` puts the change in a batch opened with `auditApi.openBatch`, so
   * work done over many requests is one event in history. */
  create: (
    datasetName: string,
    body: { schema_name: string; data: object; parent_record_id?: string },
    options?: { batchId?: string },
  ) =>
    api.post<CivexRecord>(
      `/collections/${encodeURIComponent(datasetName)}/records`,
      body,
      batchHeaders(options?.batchId),
    ),

  update: (
    id: string,
    body: { data: object },
    options?: { batchId?: string },
  ) =>
    api.patch<CivexRecord>(
      `/records/${id}`,
      body,
      batchHeaders(options?.batchId),
    ),

  delete: (id: string) => api.delete<void>(`/records/${id}`),

  deleteMany: (ids: string[]) =>
    api.post<{ deleted: number }>('/records/bulk-delete', { ids }),

  /** Deletes every record the query matches (no filters: the whole
   * collection). The same query the list shows, so "all N matching" is
   * exactly what is on screen. */
  deleteMatching: (datasetName: string, params?: RecordQueryParams) =>
    api.delete<{ deleted: number }>(
      `/collections/${encodeURIComponent(datasetName)}/records${recordQueryString(params)}`,
    ),

  /** `reachableFrom` (a collection name) limits results to records a record
   * there may reference: its own collection's and global collections'. */
  searchBySchema: (
    schemaName: string,
    search?: string,
    limit = 20,
    reachableFrom?: string,
  ) => {
    const qs = new URLSearchParams({ schema: schemaName })
    if (search) qs.set('search', search)
    if (reachableFrom) qs.set('reachable_from', reachableFrom)
    qs.set('limit', String(limit))
    return api.get<CivexRecord[]>(`/records?${qs}`)
  },

  /** Records of any schema matching `q`, best match first. Every
   * collection unless `collection` narrows it; each result carries its
   * collection's name. */
  search: (q: string, limit = 20, collection?: string) => {
    const qs = new URLSearchParams({ q, limit: String(limit) })
    if (collection) qs.set('collection', collection)
    return api.get<CivexRecord[]>(`/records/search?${qs}`)
  },

  listDeleted: (datasetName?: string) => {
    const qs = datasetName ? `?dataset=${encodeURIComponent(datasetName)}` : ''
    return api.get<CivexRecord[]>(`/records/deleted${qs}`)
  },

  restore: (id: string) => api.post<CivexRecord>(`/records/${id}/restore`, {}),
  /** Live records under a deleted record, with what they sit under. */
  orphans: (limit = 200) =>
    api.get<{ total: number; items: Orphan[] }>(
      `/records/orphans?limit=${limit}`,
    ),
  /** Bring back the deleted records a live record sits under, each by itself. */
  restoreAbove: (id: string) =>
    api.post<CivexRecord[]>(`/records/${id}/restore-above`, {}),

  /** Restore exactly these deleted records, not what was deleted alongside
   * them. The deleted records above a chosen one come back too (each by
   * itself) unless `withParents` is false, when such a record is left. */
  restoreSelected: (ids: string[], withParents = true) =>
    api.post<RestoreSelectedResult>('/records/restore-selected', {
      ids,
      with_parents: withParents,
    }),

  purge: (id: string) => api.delete<void>(`/records/${id}/purge`),

  audit: (id: string, offset = 0, limit = 50, view?: AuditView) =>
    api.get<PaginatedAuditLog>(auditUrl(`/records/${id}`, offset, limit, view)),
}
