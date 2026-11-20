import { api } from './client'
import type { FilterTreeWire } from '../utils/filterTree'
import type { SortEntry } from './query'
import type { RecordSummary } from './records'

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
  /** Set for a saved analysis: the summary the explorer opens on and the
   * Analytics page draws; null for a plain saved filter. */
  summary?: SavedSummary | null
}

/** A summary kept on a view (civex/domain/summary.py `SavedSummary`): its
 * groupings and measures as the address writes them, the table's sort, table
 * or chart and the chart's measure, and where it was made. */
export interface SavedSummary {
  group_by: string[]
  measures: string[]
  sort: { column: string; direction: 'asc' | 'desc' } | null
  show: 'table' | 'chart'
  chart_measure: string | null
  /** The collection's id; null for every collection. */
  collection: string | null
  within: string | null
  search: string | null
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
  summary?: SavedSummary | null
}

export interface UpdateViewBody {
  rename?: string
  columns?: string[]
  filter_tree?: FilterTreeWire | null
  sort?: ViewSortEntry[]
  files_layout?: FilesLayout
  /** null makes an analysis a plain saved filter again. */
  summary?: SavedSummary | null
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

  /** A saved analysis worked out now (what an Analytics card draws). */
  summary: (schemaName: string, viewName: string) =>
    api.get<RecordSummary>(
      `/schemas/${encodeURIComponent(schemaName)}/views/${encodeURIComponent(viewName)}/summary`,
    ),

  preview: (schemaName: string, body: PreviewViewBody) =>
    api.post<ViewPreview>(
      `/schemas/${encodeURIComponent(schemaName)}/views/preview`,
      body,
    ),
}
