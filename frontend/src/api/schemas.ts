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
}

export interface SchemaDeleteImpact {
  child_schema_count: number
  record_count: number
}

export const schemasApi = {
  list: () => api.get<Schema[]>('/schemas'),
  get: (name: string) => api.get<Schema>(`/schemas/${name}`),
  getDeleteImpact: (name: string) =>
    api.get<SchemaDeleteImpact>(`/schemas/${name}/delete-impact`),
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
