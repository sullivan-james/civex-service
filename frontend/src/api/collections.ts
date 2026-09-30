import { api } from './client'
import type { PaginatedAuditLog } from './audit'

export interface Collection {
  id: string
  name: string
  description: string | null
  /** IANA zone datetime values are read and shown in; null = unset. */
  timezone: string | null
  record_count: number
  /** When this collection was soft-deleted. Null means live. */
  deleted_at: string | null
}

export const collectionsApi = {
  list: () => api.get<Collection[]>('/collections'),
  get: (name: string) => api.get<Collection>(`/collections/${name}`),
  getAudit: (name: string, offset = 0, limit = 50) =>
    api.get<PaginatedAuditLog>(
      `/collections/${name}/audit?offset=${offset}&limit=${limit}`,
    ),
  create: (body: { name: string; description?: string; timezone?: string }) =>
    api.post<Collection>('/collections', body),
  update: (
    name: string,
    body: { rename?: string; description?: string; timezone?: string },
  ) => api.patch<Collection>(`/collections/${name}`, body),
  delete: (name: string) => api.delete<void>(`/collections/${name}`),
  listDeleted: () => api.get<Collection[]>('/collections/deleted'),
  restore: (name: string) =>
    api.post<Collection>(`/collections/${name}/restore`, {}),
  purge: (name: string) => api.delete<void>(`/collections/${name}/purge`),
}
