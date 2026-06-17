import { api } from './client'

export interface Field {
  id: string
  name: string
  type: string
  required: boolean
  restrictions: Record<string, string>
}

export interface Schema {
  id: string
  name: string
  description: string | null
  parent_id: string | null
  fields: Field[]
}

export const schemasApi = {
  list: ()                                           => api.get<Schema[]>('/schemas'),
  get:  (name: string)                               => api.get<Schema>(`/schemas/${name}`),
  create: (body: { name: string; description?: string; parent?: string }) =>
    api.post<Schema>('/schemas', body),
  update: (name: string, body: { rename?: string; description?: string }) =>
    api.patch<Schema>(`/schemas/${name}`, body),
  delete: (name: string)                             => api.delete<void>(`/schemas/${name}`),
  addField: (name: string, body: { name: string; type: string; required?: boolean; restrictions?: Record<string, string> }) =>
    api.post<Field>(`/schemas/${name}/fields`, body),
  updateField: (name: string, fieldName: string, body: { required: boolean }) =>
    api.patch<Field>(`/schemas/${name}/fields/${fieldName}`, body),
  deleteField: (name: string, fieldName: string) =>
    api.delete<void>(`/schemas/${name}/fields/${fieldName}`),
}
