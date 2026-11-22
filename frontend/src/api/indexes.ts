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

/** How far the server's background build has got (`GET /db/indexes`). */
export interface IndexProgress {
  done: number
  total: number
  schema_label: string
  field_label: string
  /** Waiting for a moment when nobody is saving (SQLite). */
  waiting: boolean
  /** Times a build gave way to a save and started again. */
  yielded: number
}

/** Every field that has, or should have, an index, and the build going on. */
export interface FieldIndexReport {
  fields: FieldIndex[]
  stale: string[]
  in_step: boolean
  building: boolean
  progress: IndexProgress | null
  /** Another civex process (the CLI's) is updating them. */
  elsewhere: boolean
  error: string | null
}

export const indexesApi = {
  report: () => api.get<FieldIndexReport>('/db/indexes'),
  get: (schema: string, field: string) =>
    api.get<FieldIndex>(`/schemas/${schema}/fields/${field}/index`),
  set: (schema: string, field: string, indexed: boolean) =>
    api.put<FieldIndex>(`/schemas/${schema}/fields/${field}/index`, {
      indexed,
    }),
}
