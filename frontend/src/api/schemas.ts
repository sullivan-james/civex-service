import { api } from './client'

export interface Field {
  id: string
  name: string
  /** Human-facing display name; null means "derive one from name". */
  label: string | null
  type: string
  required: boolean
  restrictions: Record<string, unknown>
  default: unknown | null
  position: number | null
}

export interface Schema {
  id: string
  name: string
  /** Human-facing display name; null means "derive one from name". */
  label: string | null
  description: string | null
  parent_id: string | null
  display_fields: string[]
  fields: Field[]
  /** When this schema was soft-deleted. Null means live. */
  deleted_at: string | null
}

export interface SchemaDeleteImpact {
  child_schema_count: number
  record_count: number
}

export interface NameIssue {
  kind: 'schema' | 'field'
  schema_name: string
  name: string
  /** Slugified alternative; null if undecidable. */
  suggestion: string | null
}

export interface AuditLogEntry {
  id: string
  commit_id: string | null
  action: string
  entity_type: string
  entity_id: string
  old_data: Record<string, unknown> | null
  new_data: Record<string, unknown> | null
  timestamp: string
}

export interface PaginatedAuditLog {
  items: AuditLogEntry[]
  total: number
  offset: number
  limit: number
}

export const schemasApi = {
  list: () => api.get<Schema[]>('/schemas'),
  lint: () => api.get<NameIssue[]>('/schemas/lint'),
  get: (name: string) => api.get<Schema>(`/schemas/${name}`),
  getDeleteImpact: (name: string) =>
    api.get<SchemaDeleteImpact>(`/schemas/${name}/delete-impact`),
  getAudit: (name: string, offset = 0, limit = 50) =>
    api.get<PaginatedAuditLog>(
      `/schemas/${name}/audit?offset=${offset}&limit=${limit}`,
    ),
  create: (body: {
    name: string
    label?: string
    description?: string
    parent?: string
    fields?: {
      name: string
      label?: string
      type: string
      required?: boolean
      restrictions?: Record<string, unknown>
      default?: unknown
    }[]
  }) => api.post<Schema>('/schemas', body),
  update: (
    name: string,
    body: {
      rename?: string
      // '' clears the label; omit the key to leave it unchanged.
      label?: string
      description?: string
      display_fields?: string[] | null
    },
  ) => api.patch<Schema>(`/schemas/${name}`, body),
  delete: (name: string) => api.delete<void>(`/schemas/${name}`),
  listDeleted: () => api.get<Schema[]>('/schemas/deleted'),
  restore: (name: string) => api.post<Schema>(`/schemas/${name}/restore`, {}),
  purge: (name: string) => api.delete<void>(`/schemas/${name}/purge`),
  addField: (
    name: string,
    body: {
      name: string
      label?: string
      type: string
      required?: boolean
      restrictions?: Record<string, unknown>
      default?: unknown
    },
  ) => api.post<Field>(`/schemas/${name}/fields`, body),
  updateField: (
    name: string,
    fieldName: string,
    body: {
      rename?: string
      // '' clears the label; omit the key to leave it unchanged.
      label?: string
      required?: boolean
      restrictions?: Record<string, unknown> | null
    },
  ) => api.patch<Field>(`/schemas/${name}/fields/${fieldName}`, body),
  deleteField: (name: string, fieldName: string) =>
    api.delete<void>(`/schemas/${name}/fields/${fieldName}`),
  reorderFields: (name: string, order: string[]) =>
    api.put<void>(`/schemas/${name}/fields/reorder`, { order }),
}
