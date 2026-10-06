import { api } from './client'
import type { FilterTreeWire } from '../utils/filterTree'
import type { TableSpec } from './fileAccess'
import type { FilesLayout } from './views'

/** An export saved with a schema: which kind of record holds the files, which
 * file fields, a filter on those records, and a layout. It says nothing about
 * which collection or record it runs on. */
export interface ExportDefinition {
  id: string
  schema_id: string
  /** The schema it is saved with. */
  schema_name: string
  name: string
  /** The kind of record that holds the files; null means any kind beneath. */
  holder: string | null
  /** The file fields exported; empty means every file field. */
  fields: string[]
  filter_tree: FilterTreeWire | null
  files_layout: FilesLayout
  /** false: the export is a table alone. */
  include_files: boolean
  /** The tables made beside the files (or instead of them). */
  tables: TableSpec[]
}

export interface CreateExportDefinition {
  name: string
  holder?: string | null
  fields?: string[]
  filter_tree?: FilterTreeWire | null
  files_layout?: FilesLayout
  include_files?: boolean
  tables?: TableSpec[]
}

export interface UpdateExportDefinition {
  rename?: string
  holder?: string | null
  fields?: string[]
  filter_tree?: FilterTreeWire | null
  files_layout?: FilesLayout
  include_files?: boolean
  tables?: TableSpec[]
}

const base = (schema: string) =>
  `/schemas/${encodeURIComponent(schema)}/exports`

export const exportDefinitionsApi = {
  list: (schema: string) => api.get<ExportDefinition[]>(base(schema)),

  create: (schema: string, body: CreateExportDefinition) =>
    api.post<ExportDefinition>(base(schema), body),

  update: (schema: string, name: string, body: UpdateExportDefinition) =>
    api.patch<ExportDefinition>(
      `${base(schema)}/${encodeURIComponent(name)}`,
      body,
    ),

  delete: (schema: string, name: string) =>
    api.delete<void>(`${base(schema)}/${encodeURIComponent(name)}`),

  /** Every export saved, whatever schema it is saved with. */
  all: () => api.get<ExportDefinition[]>('/file-access/definitions'),

  /** The exports to offer where a person is: on a record of `schema` (those saved
   * with it or a schema above it whose files are at or beneath it), or on a
   * collection (those saved with any schema it is for). */
  available: (where: { schema: string } | { collection: string }) =>
    api.get<ExportDefinition[]>(
      `/file-access/definitions?${new URLSearchParams(where)}`,
    ),
}
