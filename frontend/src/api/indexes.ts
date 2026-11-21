import { api } from './client'

/** A field's index in this computer's database (`IndexService`). */
export interface FieldIndex {
  field_id: string
  field: string
  schema_name: string
  /** It has, or is about to have, an index. */
  indexed: boolean
  /** Why: `unique_key` (always indexed) and/or `chosen`. */
  reasons: string[]
  /** The index is in the database (it is built in the background). */
  built: boolean
  /** A single-valued type: only those can be indexed. */
  indexable: boolean
}

export const indexesApi = {
  get: (schema: string, field: string) =>
    api.get<FieldIndex>(`/schemas/${schema}/fields/${field}/index`),
  set: (schema: string, field: string, indexed: boolean) =>
    api.put<FieldIndex>(`/schemas/${schema}/fields/${field}/index`, {
      indexed,
    }),
}
