import { api } from './client'
import type { FilterTreeWire } from '../utils/filterTree'

export interface ViewSortEntry {
  field: string
  direction: 'asc' | 'desc'
}

export interface View {
  id: string
  schema_id: string
  schema_name: string
  name: string
  columns: string[]
  filter_tree: FilterTreeWire | null
  sort: ViewSortEntry[]
}

export interface ViewPreview {
  rows: Record<string, unknown>[]
  total: number
}

export interface CreateViewBody {
  name: string
  columns?: string[]
  filter_tree?: FilterTreeWire | null
  sort?: ViewSortEntry[]
}

export interface UpdateViewBody {
  rename?: string
  columns?: string[]
  filter_tree?: FilterTreeWire | null
  sort?: ViewSortEntry[]
}

export interface PreviewViewBody {
  columns?: string[]
  filter_tree?: FilterTreeWire | null
  sort?: ViewSortEntry[]
  limit?: number
  offset?: number
}

export const viewsApi = {
  listAll: () => api.get<View[]>('/views'),

  list: (schemaName: string) =>
    api.get<View[]>(`/schemas/${encodeURIComponent(schemaName)}/views`),

  get: (schemaName: string, viewName: string) =>
    api.get<View>(
      `/schemas/${encodeURIComponent(schemaName)}/views/${encodeURIComponent(viewName)}`,
    ),

  create: (schemaName: string, body: CreateViewBody) =>
    api.post<View>(`/schemas/${encodeURIComponent(schemaName)}/views`, body),

  update: (schemaName: string, viewName: string, body: UpdateViewBody) =>
    api.patch<View>(
      `/schemas/${encodeURIComponent(schemaName)}/views/${encodeURIComponent(viewName)}`,
      body,
    ),

  delete: (schemaName: string, viewName: string) =>
    api.delete<void>(
      `/schemas/${encodeURIComponent(schemaName)}/views/${encodeURIComponent(viewName)}`,
    ),

  preview: (schemaName: string, body: PreviewViewBody) =>
    api.post<ViewPreview>(
      `/schemas/${encodeURIComponent(schemaName)}/views/preview`,
      body,
    ),
}
