import type { AuditChange } from './audit'
import { ApiError, api } from './client'
import {
  filenameOf,
  progressHeaders,
  type FileExportResult,
  type FilePlanSummary,
  type GatherResult,
} from './fileAccess'
import { apiUrl } from '../utils/host'

/** What a release covers: the whole project (`{}`), some collections, the
 * records a query lists, or chosen records (each with the records above it). */
export interface ReleaseScope {
  collections?: string[]
  query?: Record<string, unknown>
  records?: string[]
}

/** One author, as cited. */
export interface ReleaseAuthor {
  name: string
  orcid?: string
  affiliation?: string
}

/** A frozen, citable copy of the data (`GET /releases`). */
export interface Release {
  id: string
  name: string
  title: string
  description: string | null
  authors: ReleaseAuthor[]
  licence: string | null
  doi: string | null
  keywords: string[]
  scope: ReleaseScope
  content_hash: string
  bundle_sha256: string
  bundle_size: number
  counts: Record<string, number | string[]>
  local_seq: number | null
  feed_seq: number | null
  civex_version: string
  created_at: string
  created_by: string | null
  updated_at: string | null
  withdrawn_at: string | null
  withdrawn_by: string | null
  withdrawn_reason: string | null
  /** When its data was given up: what is left is this record of it. */
  yanked_at: string | null
  yanked_by: string | null
  yanked_reason: string | null
  file_name: string
  /** Comparing it with the data now is long: run it as a job. */
  compare_in_background: boolean
}

export interface ReleaseScopeBody {
  collections?: string[] | null
  query?: Record<string, unknown> | null
  records?: string[] | null
  include_workflows?: boolean
}

export interface ReleaseMetadata {
  title?: string
  description?: string | null
  authors?: ReleaseAuthor[]
  licence?: string | null
  doi?: string | null
  keywords?: string[]
}

/** What a release of a scope would hold, from the catalog (nothing is read
 * from a drive): records per collection, the files they cite by drive, and
 * the history position it would be taken at. */
export interface ReleasePlan {
  records: number
  collections: Record<string, number>
  schemas: number
  files: number
  file_bytes: number
  /** Where the cited files are; `volume` null for ones not on this computer. */
  by_drive: { volume: string | null; files: number; bytes: number }[]
  workflows: number
  plugins: number
  feed_seq: number | null
  local_seq: number
  /** Changes the server hasn't got: a release can't be made while any wait. */
  unsent: number
}

/** What yanking would give up, counted by the clean-up's own rule. */
export interface YankPlan {
  name: string
  files: number
  unused_files: number
  unused_bytes: number
  kept_files: number
}

export interface ReleaseFilePlan extends FilePlanSummary {
  /** Small enough to download as one zip. */
  zip_allowed: boolean
}

export interface ReleaseCreateBody extends ReleaseScopeBody, ReleaseMetadata {
  name: string
  title: string
}

export interface ReleaseCitation {
  text: string
  bibtex: string
  cff: string
}

export interface ReleaseVerify {
  name: string
  matches: boolean
  expected: string
  actual: string | null
  bundle_intact: boolean
  files: number
  files_not_here: number
  files_unchecked: number
  files_read: number
  files_bad: string[]
  deep: boolean
  problems: string[]
  notes: string[]
}

export interface CollectionComparison {
  collection_id: string
  collection: string | null
  added: number
  changed: number
  removed: number
  in_scope: boolean
}

export interface StructureChange {
  kind: 'schema' | 'field'
  change: 'added' | 'removed' | 'changed'
  name: string | null
  schema: string | null
  what: string[]
}

/** A release compared with the data now, record by record. */
export interface ReleaseComparison {
  name: string
  records: number
  unchanged: number
  added: number
  changed: number
  removed: number
  collections: CollectionComparison[]
  structure: StructureChange[]
  at: number
}

export type ComparedKind = 'added' | 'changed' | 'removed'

export interface ComparedRecord {
  id: string
  name: string | null
  collection: string | null
  schema: string | null
  live: boolean
}

const at = (name: string) => `/releases/${encodeURIComponent(name)}`

export const releasesApi = {
  list: () => api.get<Release[]>('/releases'),
  get: (name: string) => api.get<Release>(at(name)),
  plan: (body: ReleaseScopeBody) =>
    api.post<ReleasePlan>('/releases/plan', body),
  /** How a release with these details would be cited, before it is made. */
  preview: (body: ReleaseMetadata & { name: string }) =>
    api.post<ReleaseCitation>('/releases/citation-preview', body),
  create: (body: ReleaseCreateBody, progressId?: string) =>
    api.post<Release>('/releases', body, progressHeaders(progressId)),
  correct: (name: string, body: ReleaseMetadata) =>
    api.patch<Release>(at(name), body),
  withdraw: (name: string, reason: string) =>
    api.post<Release>(`${at(name)}/withdraw`, { reason }),
  planYank: (name: string) => api.get<YankPlan>(`${at(name)}/yank`),
  yank: (name: string, reason: string) =>
    api.post<Release>(`${at(name)}/yank`, { reason }),
  citation: (name: string) => api.get<ReleaseCitation>(`${at(name)}/citation`),
  verify: (name: string, deep = false, progressId?: string) =>
    api.post<ReleaseVerify>(
      `${at(name)}/verify${deep ? '?deep=true' : ''}`,
      {},
      progressHeaders(progressId),
    ),
  filePlan: (name: string) =>
    api.post<ReleaseFilePlan>(`${at(name)}/files/plan`, {}),
  exportFiles: (
    name: string,
    body: {
      mode: 'link' | 'copy'
      volume?: string
      allow_partial?: boolean
      open?: boolean
    },
    progressId?: string,
  ) =>
    api.post<FileExportResult>(
      `${at(name)}/files/export`,
      body,
      progressHeaders(progressId),
    ),
  zipFiles: async (
    name: string,
    allowPartial: boolean,
    progressId?: string,
  ) => {
    const res = await fetch(
      apiUrl(`${at(name)}/files/zip?allow_partial=${allowPartial}`),
      { method: 'POST', headers: progressHeaders(progressId) },
    )
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new ApiError(body.detail, res.status, body)
    }
    return { blob: await res.blob(), filename: filenameOf(res) }
  },
  gatherFiles: (name: string, volume: string) =>
    api.post<GatherResult>(`${at(name)}/files/gather`, { volume }),
  compare: (name: string, progressId?: string) =>
    api.post<ReleaseComparison>(
      `${at(name)}/compare`,
      {},
      progressHeaders(progressId),
    ),
  comparedRecords: (
    name: string,
    kind: ComparedKind,
    offset: number,
    limit: number,
    collection?: string,
  ) => {
    const q = new URLSearchParams({
      kind,
      offset: String(offset),
      limit: String(limit),
    })
    if (collection) q.set('collection', collection)
    return api.get<{ total: number; items: ComparedRecord[] }>(
      `${at(name)}/compare/records?${q}`,
    )
  },
  recordDifferences: (name: string, id: string) =>
    api.get<AuditChange[]>(
      `${at(name)}/compare/records/${encodeURIComponent(id)}`,
    ),
  /** Where the bundle downloads from (fetched from the server first on a
   * copy that hasn't got it). */
  bundleUrl: (name: string) => apiUrl(`${at(name)}/bundle`),
  /** Writes its copy straight onto a drive of this computer (none: the
   * project folder). */
  save: (name: string, volume: string | null) =>
    api.post<{ path: string; opened: boolean }>(`${at(name)}/save`, { volume }),
}
