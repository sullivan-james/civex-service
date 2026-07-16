import { api } from './client'

export interface Field {
  id: string
  name: string
  type: string
  required: boolean
  restrictions: Record<string, unknown>
  default: unknown | null
  position: number | null
}

export interface Schema {
  id: string
  name: string
  description: string | null
  parent_id: string | null
  display_field: string | null
  fields: Field[]
}

export const schemasApi = {
  list: ()                                           => api.get<Schema[]>('/schemas'),
  get:  (name: string)                               => api.get<Schema>(`/schemas/${name}`),
  create: (body: { name: string; description?: string; parent?: string }) =>
    api.post<Schema>('/schemas', body),
  update: (name: string, body: { rename?: string; description?: string; display_field?: string | null }) =>
    api.patch<Schema>(`/schemas/${name}`, body),
  delete: (name: string)                             => api.delete<void>(`/schemas/${name}`),
  addField: (name: string, body: { name: string; type: string; required?: boolean; restrictions?: Record<string, unknown>; default?: unknown }) =>
    api.post<Field>(`/schemas/${name}/fields`, body),
  updateField: (name: string, fieldName: string, body: { rename?: string; required?: boolean; restrictions?: Record<string, unknown> | null }) =>
    api.patch<Field>(`/schemas/${name}/fields/${fieldName}`, body),
  deleteField: (name: string, fieldName: string) =>
    api.delete<void>(`/schemas/${name}/fields/${fieldName}`),
  reorderFields: (name: string, order: string[]) =>
    api.put<void>(`/schemas/${name}/fields/reorder`, { order }),
}
