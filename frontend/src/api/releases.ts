import { api } from './client'
import type { BundlePlan } from './bundle'
import { apiUrl } from '../utils/host'

/** What a release covers: the whole project (`{}`), some collections, or the
 * records a query lists. */
export interface ReleaseScope {
  collections?: string[]
  query?: Record<string, unknown>
}

/** A frozen, citable copy of the data (`GET /releases`). */
export interface Release {
  id: string
  name: string
  title: string
  description: string | null
  authors: string[]
  licence: string | null
  doi: string | null
  scope: ReleaseScope
  include_files: boolean
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
  file_name: string
}

export interface ReleaseScopeBody {
  collections?: string[] | null
  include_files?: boolean
  include_workflows?: boolean
}

export interface ReleaseMetadata {
  title?: string
  description?: string | null
  authors?: string[]
  licence?: string | null
  doi?: string | null
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
  problems: string[]
}

export interface CollectionChanges {
  collection_id: string | null
  collection: string | null
  added: number
  changed: number
  deleted: number
  in_scope: boolean
}

export interface ReleaseChanges {
  name: string
  comparable: boolean
  by: 'feed' | 'local' | null
  reason: string | null
  added: number
  changed: number
  deleted: number
  collections: CollectionChanges[]
  structure: Record<string, number>
}

const at = (name: string) => `/releases/${encodeURIComponent(name)}`

export const releasesApi = {
  list: () => api.get<Release[]>('/releases'),
  get: (name: string) => api.get<Release>(at(name)),
  plan: (body: ReleaseScopeBody) =>
    api.post<BundlePlan>('/releases/plan', body),
  create: (body: ReleaseCreateBody) => api.post<Release>('/releases', body),
  correct: (name: string, body: ReleaseMetadata) =>
    api.patch<Release>(at(name), body),
  withdraw: (name: string, reason: string) =>
    api.post<Release>(`${at(name)}/withdraw`, { reason }),
  citation: (name: string) => api.get<ReleaseCitation>(`${at(name)}/citation`),
  verify: (name: string) => api.post<ReleaseVerify>(`${at(name)}/verify`, {}),
  changes: (name: string) => api.get<ReleaseChanges>(`${at(name)}/changes`),
  /** Where the bundle downloads from (fetched from the server first on a
   * copy that hasn't got it). */
  bundleUrl: (name: string) => apiUrl(`${at(name)}/bundle`),
}
