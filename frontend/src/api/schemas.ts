import { api } from './client'
import type { PaginatedAuditLog } from './audit'

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

/** One rule a field of some type can carry; see `domain/field_descriptors.py`. */
export interface RestrictionDescriptor {
  key: string
  label: string
  /** Which editor to show (number, bytes, choices, accept, bbox, ...). */
  control: string
  help: string
}

export interface FieldTypeDescriptor {
  type: string
  label: string
  description: string
  stored_as: string
  /** One line shown beside the input on the record page. */
  entry_hint: string
  example: string
  restrictions: RestrictionDescriptor[]
  supports_default: boolean
}

/** An entry in the "what kind of data is this?" picker. */
export interface FieldKind {
  key: string
  label: string
  type: string
  description: string
  /** Restriction the editor leads with for this kind. */
  focus: string | null
}

export interface FieldTypes {
  types: FieldTypeDescriptor[]
  kinds: FieldKind[]
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

export const schemasApi = {
  list: () => api.get<Schema[]>('/schemas'),
  lint: () => api.get<NameIssue[]>('/schemas/lint'),
  fieldTypes: () => api.get<FieldTypes>('/schemas/field-types'),
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
