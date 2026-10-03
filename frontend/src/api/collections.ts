import { api } from './client'
import { auditUrl, type PaginatedAuditLog } from './audit'
import type { TableQueryParams } from './query'

export interface Collection {
  id: string
  name: string
  description: string | null
  /** IANA zone datetime values are read and shown in; null = unset. */
  timezone: string | null
  record_count: number
  /** When this collection was soft-deleted. Null means live. */
  deleted_at: string | null
  /** 'local': only this collection's records can reference its records.
   * 'global': records in any collection can. */
  scope: CollectionScope
  /** Schemas the collection is for; its records can only be of these. */
  schemas: string[]
}

export type CollectionScope = 'local' | 'global'

export const collectionsApi = {
  list: () => api.get<Collection[]>('/collections'),
  get: (name: string) => api.get<Collection>(`/collections/${name}`),
  getAudit: (name: string, offset = 0, limit = 50, table?: TableQueryParams) =>
    api.get<PaginatedAuditLog>(
      auditUrl(`/collections/${name}`, offset, limit, table),
    ),
  create: (body: {
    name: string
    description?: string
    timezone?: string
    scope?: CollectionScope
    schemas?: string[]
  }) => api.post<Collection>('/collections', body),
  update: (
    name: string,
    body: {
      rename?: string
      description?: string
      timezone?: string
      scope?: CollectionScope
      schemas?: string[]
    },
  ) => api.patch<Collection>(`/collections/${name}`, body),
  delete: (name: string) => api.delete<void>(`/collections/${name}`),
  listDeleted: () => api.get<Collection[]>('/collections/deleted'),
  restore: (name: string) =>
    api.post<Collection>(`/collections/${name}/restore`, {}),
  purge: (name: string) => api.delete<void>(`/collections/${name}/purge`),
}
