import { api } from './client'
import type { FilterTreeWire } from '../utils/filterTree'
import type { SortEntry } from './query'

export type ViewSortEntry = SortEntry

export interface View {
  id: string
  schema_id: string
  schema_name: string
  name: string
  columns: string[]
  filter_tree: FilterTreeWire | null
  sort: ViewSortEntry[]
  /** How the view's files are arranged when exported as a folder or zip: a
   * folder per record above each file, or all in one folder. */
  files_layout: FilesLayout
}

export type FilesLayout = 'tree' | 'grouped' | 'flat'

export interface ViewPreview {
  rows: Record<string, unknown>[]
  total: number
}

export interface CreateViewBody {
  name: string
  columns?: string[]
  filter_tree?: FilterTreeWire | null
  sort?: ViewSortEntry[]
  files_layout?: FilesLayout
}

export interface UpdateViewBody {
  rename?: string
  columns?: string[]
  filter_tree?: FilterTreeWire | null
  sort?: ViewSortEntry[]
  files_layout?: FilesLayout
}

export interface PreviewViewBody {
  columns?: string[]
  filter_tree?: FilterTreeWire | null
  sort?: ViewSortEntry[]
  limit?: number
  offset?: number
}

export const viewsApi = {
  /** Every saved view across every schema. */
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
