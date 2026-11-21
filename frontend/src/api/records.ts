import { api, ApiError } from './client'
import { apiUrl } from '../utils/host'
import { UploadConnectionError, type UploadInfo } from './files'
import { filenameOf, progressHeaders } from './fileAccess'
import type { Field } from './schemas'
import { auditUrl, type AuditView, type PaginatedAuditLog } from './audit'
import {
  recordQueryString,
  type PageParams,
  type RecordQueryParams,
} from './query'
import type { FilterTreeWire } from '../utils/filterTree'

/** Which records: exactly `ids`, or every record the query (`collection`
 * with the list's selectors) shows. */
export interface RecordSelectionBody {
  ids?: string[] | null
  collection?: string | null
  schema_name?: string | null
  within?: string | null
  filter?: FilterTreeWire | null
  where?: string[]
  search?: string | null
  search_fields?: string[] | null
}

/** The records a person chose in a list: the rows ticked, or everything the
 * list's query shows. */
export type RecordSelection =
  { ids: string[] } | { query: RecordQueryParams; collection: string }

/** A selection as the request body every bulk action takes. */
export function selectionBody(selection: RecordSelection): RecordSelectionBody {
  if ('ids' in selection) return { ids: selection.ids }
  return queryBody(selection.query, selection.collection)
}

/** A list's query as the request body every query endpoint takes (no
 * collection: every collection). */
export function queryBody(
  q: RecordQueryParams,
  collection?: string | null,
): RecordSelectionBody {
  return {
    collection: collection ?? null,
    schema_name: q.schema ?? null,
    within: q.within ?? null,
    filter: q.filter ?? null,
    where: q.where ?? [],
    search: q.search ?? null,
    search_fields: q.search_fields ?? null,
  }
}

/** Summarise the records a query lists: `group_by` and `measures` are
 * written as the CLI and the explorer's address write them (`site.region`,
 * `taken:month`, `depth:5`; `count`, `mean:depth`). */
export interface SummaryRequest extends RecordSelectionBody {
  group_by: string[]
  measures: string[]
  limit?: number
}

export interface SummaryGroupColumn {
  key: string
  field: string
  schema_name: string
  label: string
  type: string
  bucket: string | null
  bin: number | null
  unit: string | null
}

export interface SummaryMeasureColumn {
  key: string
  measure: string
  label: string
  field: string | null
  schema_name: string | null
  type: string | null
  unit: string | null
}

/** One group's value for one grouping. `lower`/`upper` bound a range or a
 * period (upper excluded); `precision` is set for a date less precise than
 * the period grouped by. */
export interface SummaryGroupValue {
  value: unknown
  label: string
  lower: unknown
  upper: unknown
  precision: string | null
}

export interface SummaryRow {
  groups: SummaryGroupValue[]
  values: unknown[]
  /** The filter condition listing exactly this group's records (null when a
   * filter can't say it: an item of a list). */
  where: FilterTreeWire | null
}

export interface RecordSummary {
  schema_name: string
  group_columns: SummaryGroupColumn[]
  measure_columns: SummaryMeasureColumn[]
  rows: SummaryRow[]
  total: unknown[]
  truncated: boolean
  limit: number
  timezone: string | null
}

/** Where the records a query lists are, for a map: `field` is a location
 * field of the kind listed, or (`field_schema`) of a kind above it. */
/** Data checks (`POST /records/quality`): what needs a look in the records a
 * query lists, per kind and field. */
export interface QualityExample {
  record_id: string
  record_name: string | null
  message: string
}

export interface QualityIssue {
  issue: string
  field: string
  field_label: string
  count: number
  examples: QualityExample[]
  /** Lists exactly these records in the explorer, when a filter can say it. */
  filter: FilterTreeWire | null
}

export interface QualityBlanks {
  field: string
  field_label: string
  required: boolean
  blank: number
  filter: FilterTreeWire | null
}

export interface QualityKind {
  schema_name: string
  schema_label: string
  records: number
  records_with_issues: number
  issues: QualityIssue[]
  blanks: QualityBlanks[]
}

export interface QualityIssueKind {
  name: string
  label: string
  description: string
}

export interface QualityReport {
  records: number
  records_with_issues: number
  kinds: QualityKind[]
  issues: QualityIssueKind[]
}

export interface QualityRecordsRequest extends RecordSelectionBody {
  issue: string
  field?: string | null
  kind?: string | null
  limit?: number
  offset?: number
}

export interface QualityFinding {
  record_id: string
  record_name: string | null
  schema_name: string
  field: string
  message: string
}

export interface QualityRecords {
  items: QualityFinding[]
  total: number
  offset: number
  limit: number
}

export interface PointsRequest extends RecordSelectionBody {
  field: string
  field_schema?: string
  limit?: number
}

export interface RecordPoint {
  id: string
  name: string | null
  /** GeoJSON, WGS84 ([lon, lat]). */
  geometry: { type: string; coordinates?: unknown; geometries?: unknown }
}

export interface RecordPoints {
  schema_name: string
  field: string
  points: RecordPoint[]
  /** How many listed records have a value; more than `points` when truncated. */
  total: number
  truncated: boolean
  limit: number
}

/** Which records to move and where. */
export interface MoveRecordsRequest extends RecordSelectionBody {
  to: string
  /** The record in `to` they go inside; omit for its top level. */
  parent?: string | null
}

/** Which records to edit, and the value each field gets (null clears it). */
export interface BulkEditRequest extends RecordSelectionBody {
  changes: Record<string, unknown>
}

export interface BulkEditSkip {
  record_id: string
  name: string | null
  reason: string
}

/** What a bulk edit would do. A record takes every change or none. */
export interface BulkEditPlan {
  fields: string[]
  records: number
  changing: number
  unchanged: number
  /** Exact count; `skipped_records` names the first of them. */
  skipped: number
  skipped_records: BulkEditSkip[]
  /** Workflow runs the edit would start. */
  runs: number
  workflows: string[]
  automation_paused: boolean
  can_apply: boolean
}

export interface BulkEditResult {
  changed: number
  unchanged: number
  skipped: number
  skipped_records: BulkEditSkip[]
  runs: number
}

export interface RecordMovePlan {
  collection: string
  collection_id: string
  parent_id: string | null
  parent_name: string | null
  /** Chosen records that would move. */
  roots: number
  /** Records that would move in all, with everything beneath them. */
  records: number
  /** Chosen records already where they would go. */
  skipped: number
  /** The collections they would leave. */
  sources: string[]
  /** Why it can't be done, in plain words; empty when `can_move`. */
  problems: string[]
  can_move: boolean
}

export interface MoveRecordsResult {
  roots: number
  records: number
  collection: string
}

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
  /** Values this record's own `data` doesn't hold: its formula fields
   * (always), and, when `columns` were requested, inherited fields and
   * `ref.field` joins. */
  derived?: Record<string, unknown> | null
  /** Why a formula is blank for this record, by field name. */
  formula_errors?: Record<string, string> | null
  /** Only on a single-record fetch: the parent chain, root first. */
  ancestors?: RecordRef[] | null
  /** Only on a single-record fetch of a live record: the deleted records
   * directly above it, topmost first. Not empty means it is out of sight:
   * nothing above it lists it, and a sync server refuses it. */
  deleted_above?: RecordRef[] | null
  /** Values this record still holds for fields deleted from its schema. They
   * come back in `data` when the field is restored. */
  deleted_fields?: DeletedFieldValue[] | null
  /** How many of its threads of notes are not yet resolved. */
  open_notes?: number | null
  /** The first line of the latest thread not yet resolved. */
  latest_note?: string | null
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

/** A file to send with a record, named for the field it goes in. */
export interface FileUpload {
  field: string
  file: File
}

/** Stores one file into `field` of a record and saves the record, reporting
 * progress; what a record page hands the field grid so a file chosen there
 * is one request (`recordsApi.attachFile`). */
export type FileSaver = (
  field: Field,
  file: File,
  onProgress: (info: UploadInfo) => void,
  signal: AbortSignal,
) => Promise<CivexRecord>

export const recordsApi = {
  /** Names for any number of ids in one request. Ids that aren't records, or
   * whose record is gone, are not in the answer. */
  labels: (ids: string[]) =>
    api.post<RecordLabel[]>('/records/labels', { ids }),

  list: (datasetName: string, params?: ListParams) =>
    api.get<PaginatedRecords>(
      `/collections/${encodeURIComponent(datasetName)}/records${recordQueryString(params)}`,
    ),

  /** Records across every collection: of one schema (`params.schema`), or
   * of every kind at once. */
  listAll: (params?: ListParams) =>
    api.get<PaginatedRecords>(`/records/all${recordQueryString(params)}`),

  /** A schema's records across every collection -- what a saved view browses. */
  listBySchema: (schemaName: string, params?: ListParams) =>
    api.get<PaginatedRecords>(
      `/schemas/${encodeURIComponent(schemaName)}/records${recordQueryString(params)}`,
    ),

  /** Matching records per schema name (`within` scopes it to one record's
   * descendants). */
  /** Records per schema in a collection, or in every collection (''). */
  counts: (datasetName: string, params?: RecordQueryParams) =>
    api.get<Record<string, number>>(
      datasetName
        ? `/collections/${encodeURIComponent(datasetName)}/record-counts${recordQueryString(params)}`
        : `/records/counts${recordQueryString(params)}`,
    ),

  get: (id: string) => api.get<CivexRecord>(`/records/${id}`),

  /** What references this record, counted per collection/schema/field. */
  referrers: (id: string) =>
    api.get<ReferrerGroup[]>(`/records/${id}/referrers`),

  create: (
    datasetName: string,
    body: { schema_name: string; data: object; parent_record_id?: string },
  ) =>
    api.post<CivexRecord>(
      `/collections/${encodeURIComponent(datasetName)}/records`,
      body,
    ),

  /** A record and the files chosen for it, created as one request: the
   * record is made only if every file could be stored and the record passes
   * its checks, else nothing is kept (`POST .../records/with-files`). */
  createWithFiles: (
    datasetName: string,
    body: { schema_name: string; data: object; parent_record_id?: string },
    files: FileUpload[],
  ) => {
    const form = new FormData()
    form.append('record', JSON.stringify(body))
    for (const { field, file } of files) form.append(field, file, file.name)
    return api.upload<CivexRecord>(
      `/collections/${encodeURIComponent(datasetName)}/records/with-files`,
      form,
    )
  },

  update: (id: string, body: { data: object }) =>
    api.patch<CivexRecord>(`/records/${id}`, body),

  /** One file into a record's file field and the record saved, as one
   * request (`PUT /records/{id}/files/{field}`): appended to a list of files,
   * in place of a single file. Reports progress as `filesApi.uploadBatch`
   * does. A save civex refuses (a rule, a unique key) rejects with an
   * `ApiError` carrying the field error, and nothing was stored; a dropped
   * connection with an `UploadConnectionError`; aborting `signal` with an
   * `AbortError`. */
  attachFile: (
    id: string,
    field: string,
    file: File,
    onProgress?: (info: UploadInfo) => void,
    signal?: AbortSignal,
  ): Promise<CivexRecord> =>
    new Promise((resolve, reject) => {
      if (signal?.aborted) {
        reject(new DOMException('Upload cancelled', 'AbortError'))
        return
      }
      const query = new URLSearchParams({
        name: file.name,
        size: String(file.size),
      })
      const xhr = new XMLHttpRequest()
      xhr.open(
        'PUT',
        apiUrl(`/records/${id}/files/${encodeURIComponent(field)}?${query}`),
      )
      xhr.upload.onprogress = (e) =>
        onProgress?.({ loaded: e.loaded, total: file.size, saving: false })
      xhr.upload.onload = () =>
        onProgress?.({ loaded: file.size, total: file.size, saving: true })
      signal?.addEventListener('abort', () => xhr.abort(), { once: true })
      xhr.onabort = () =>
        reject(new DOMException('Upload cancelled', 'AbortError'))
      xhr.onload = () => {
        let body: Record<string, unknown> = {}
        try {
          body = JSON.parse(xhr.responseText)
        } catch {
          /* not JSON */
        }
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(body as unknown as CivexRecord)
        } else if (xhr.status === 502 || xhr.status === 504) {
          reject(
            new UploadConnectionError(`Couldn't reach civex (${xhr.status})`),
          )
        } else {
          reject(
            new ApiError(body.detail ?? `HTTP ${xhr.status}`, xhr.status, body),
          )
        }
      }
      xhr.onerror = () =>
        reject(new UploadConnectionError("Couldn't reach civex"))
      xhr.send(file)
    }),

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

  /** What moving the chosen records (ids, or everything a query lists) to
   * another collection would do: how many go, with everything beneath
   * them, and anything in the way. The same rule as the move itself. */
  movePlan: (body: MoveRecordsRequest) =>
    api.post<RecordMovePlan>('/records/move/plan', body),

  /** Re-points the chosen records (with everything beneath them) at another
   * collection, or inside another record. Refused whole (422) when
   * anything is in the way. */
  move: (body: MoveRecordsRequest) =>
    api.post<MoveRecordsResult>('/records/move', body),

  /** What setting (or clearing) fields on the chosen records would do: how
   * many change, how many already hold the values, which can't and why, and
   * how many workflow runs would start. The same rule as the edit. */
  /** Group the records a query lists and work out measures over each group. */
  summary: (body: SummaryRequest) =>
    api.post<RecordSummary>('/records/summary', body),

  /** What needs a look in the records a query lists (nothing is changed). */
  quality: (body: RecordSelectionBody) =>
    api.post<QualityReport>('/records/quality', body),

  /** The records a query lists that have one issue, a page at a time. */
  qualityRecords: (body: QualityRecordsRequest) =>
    api.post<QualityRecords>('/records/quality/records', body),

  /** Where the records a query lists are (id, name, geometry), for a map. */
  points: (body: PointsRequest) =>
    api.post<RecordPoints>('/records/points', body),

  /** The same summary as a table file (a last row of totals). */
  summaryFile: async (body: SummaryRequest, format: string) => {
    const res = await fetch(
      apiUrl(`/records/summary?format=${encodeURIComponent(format)}`),
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
    )
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}))
      throw new ApiError(detail.detail, res.status, detail)
    }
    return { blob: await res.blob(), filename: filenameOf(res) }
  },

  bulkEditPlan: (body: BulkEditRequest) =>
    api.post<BulkEditPlan>('/records/bulk-edit/plan', body),

  /** Sets the fields on every chosen record that can take them; the others
   * are named in the answer. Tag it with a progress id to follow it. */
  bulkEdit: (body: BulkEditRequest, progressId?: string) =>
    api.post<BulkEditResult>(
      '/records/bulk-edit',
      body,
      progressHeaders(progressId),
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
