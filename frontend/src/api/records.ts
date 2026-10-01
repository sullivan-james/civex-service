import { api } from './client'
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
}

export interface RecordRef {
  id: string
  schema_name: string
  natural_name: string | null
}

export interface PaginatedRecords {
  items: CivexRecord[]
  total: number
  offset: number
  limit: number
}

export interface AuditLogEntry {
  id: string
  commit_id: string | null
  action: string
  entity_type: string
  entity_id: string
  /** Full record snapshot before the change (record id/data/timestamps). Null on create. */
  old_data: Record<string, unknown> | null
  /** Full record snapshot after the change. Null on delete. */
  new_data: Record<string, unknown> | null
  timestamp: string
}

export interface PaginatedAuditLog {
  items: AuditLogEntry[]
  total: number
  offset: number
  limit: number
}

export type ListParams = RecordQueryParams & PageParams

export const recordsApi = {
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

  create: (
    datasetName: string,
    body: { schema_name: string; data: object; parent_record_id?: string },
  ) =>
    api.post<CivexRecord>(
      `/collections/${encodeURIComponent(datasetName)}/records`,
      body,
    ),

  update: (id: string, body: { data: object }) =>
    api.patch<CivexRecord>(`/records/${id}`, body),

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

  exportCsvUrl: (datasetName: string, params?: RecordQueryParams) =>
    `/api/collections/${encodeURIComponent(datasetName)}/export.csv${recordQueryString(params)}`,

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

  purge: (id: string) => api.delete<void>(`/records/${id}/purge`),

  audit: (id: string, offset = 0, limit = 50) =>
    api.get<PaginatedAuditLog>(
      `/records/${id}/audit?offset=${offset}&limit=${limit}`,
    ),
}
