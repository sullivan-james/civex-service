import { api } from './client'

export interface CivexRecord {
  id: string
  dataset_id: string
  schema_name: string
  parent_record_id: string | null
  data: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface PaginatedRecords {
  items: CivexRecord[]
  total: number
  offset: number
  limit: number
}

export interface ListParams {
  schema?: string
  parent_record_id?: string
  search?: string
  where?: string[]
  limit?: number
  offset?: number
}

export const recordsApi = {
  list: (datasetName: string, params?: ListParams) => {
    const qs = new URLSearchParams()
    if (params?.schema) qs.set('schema', params.schema)
    if (params?.parent_record_id) qs.set('parent_record_id', params.parent_record_id)
    if (params?.search) qs.set('search', params.search)
    params?.where?.forEach(w => qs.append('where', w))
    if (params?.limit != null) qs.set('limit', String(params.limit))
    if (params?.offset != null) qs.set('offset', String(params.offset))
    const query = qs.toString() ? `?${qs}` : ''
    return api.get<PaginatedRecords>(`/datasets/${encodeURIComponent(datasetName)}/records${query}`)
  },

  counts: (datasetName: string) =>
    api.get<Record<string, number>>(`/datasets/${encodeURIComponent(datasetName)}/record-counts`),

  get:    (id: string) => api.get<CivexRecord>(`/records/${id}`),

  create: (datasetName: string, body: { schema_name: string; data: object; parent_record_id?: string }) =>
    api.post<CivexRecord>(`/datasets/${encodeURIComponent(datasetName)}/records`, body),

  update: (id: string, body: { data: object }) => api.patch<CivexRecord>(`/records/${id}`, body),

  delete: (id: string) => api.delete<void>(`/records/${id}`),

}
