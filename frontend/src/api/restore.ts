import { api } from './client'

export type RestoreKind = 'record' | 'collection' | 'schema'

/** The deleted collection, schema or record standing in the way of a restore. */
export interface Blocker {
  kind: RestoreKind
  id: string
  /** A name, or for a record what it is called. */
  name: string
}

/** What restoring something would do, worked out without doing it. */
export interface RestorePlan {
  kind: RestoreKind
  id: string
  name: string
  /** How many records come back: those deleted together with this, the record
   * itself included when it is one. */
  records: number
  blocked_by: Blocker | null
  /** Why it can't be restored yet, in the server's words. */
  blocked: string | null
  /** For a record, the collection it will be in. */
  collection: string | null
  collection_id: string | null
  can_restore: boolean
}

/** How to ask for a thing: a record by id, a collection or schema by name. */
export interface RestoreTarget {
  kind: RestoreKind
  ref: string
}

const PATHS: Record<RestoreKind, string> = {
  record: '/records',
  collection: '/collections',
  schema: '/schemas',
}

export const restoreApi = {
  plan: ({ kind, ref }: RestoreTarget) =>
    api.get<RestorePlan>(
      `${PATHS[kind]}/${encodeURIComponent(ref)}/restore-plan`,
    ),

  restore: ({ kind, ref }: RestoreTarget) =>
    api.post<unknown>(`${PATHS[kind]}/${encodeURIComponent(ref)}/restore`, {}),
}

/** The target for a blocker, which is what to restore first. */
export function blockerTarget(b: Blocker): RestoreTarget {
  return { kind: b.kind, ref: b.kind === 'record' ? b.id : b.name }
}
