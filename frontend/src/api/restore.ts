import { api } from './client'

export type RestoreKind = 'record' | 'collection' | 'schema' | 'field'

/** What can stand in the way of a restore: a deleted collection, schema or
 * record above the thing. */
export type BlockerKind = 'record' | 'collection' | 'schema'

/** The deleted collection, schema or record standing in the way of a restore. */
export interface Blocker {
  kind: BlockerKind
  id: string
  /** A name, or for a record what it is called. */
  name: string
}

/** Another record has taken the unique values of one that would come back
 * (the schema's uniqueness rule), so restoring is refused. */
export interface RestoreConflict {
  /** The record that can't come back: the one asked for, or one below it. */
  record_id: string
  record_name: string
  /** The live record that now holds the values. */
  existing_id: string
  existing_name: string
  fields: string[]
  message: string
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
  /** For a field, the schema it belongs to. */
  schema_name: string | null
  /** For a record held back only by deleted records above it: how many of
   * them. Each can come back by itself, so restoring just this record brings
   * back `parents_needed + 1` and leaves its deleted siblings. */
  parents_needed?: number | null
  /** Set when restoring would break a uniqueness rule. */
  conflict?: RestoreConflict | null
  /** When it was deleted. */
  deleted_at?: string | null
  can_restore: boolean
}

/** How to ask for a thing: a record or field by id, a collection or schema by
 * name. A field is restored on the schema it was deleted from. */
export interface RestoreTarget {
  kind: RestoreKind
  ref: string
  /** For a field: the schema it was deleted from. */
  schema?: string
  /** Restore just this record, not what was deleted alongside it. */
  onlyThis?: boolean
  /** Restore the deleted records above it too (each by itself), so it can
   * come back without its deleted siblings. */
  withParents?: boolean
}

const PATHS: Record<Exclude<RestoreKind, 'field'>, string> = {
  record: '/records',
  collection: '/collections',
  schema: '/schemas',
}

function pathOf({ kind, ref, schema }: RestoreTarget): string {
  if (kind === 'field')
    return `/schemas/${encodeURIComponent(schema ?? '')}/fields/${encodeURIComponent(ref)}`
  return `${PATHS[kind]}/${encodeURIComponent(ref)}`
}

function restoreQuery({ onlyThis, withParents }: RestoreTarget): string {
  const qs = new URLSearchParams()
  if (onlyThis) qs.set('only_this', 'true')
  if (withParents) qs.set('with_parents', 'true')
  const text = qs.toString()
  return text ? `?${text}` : ''
}

export const restoreApi = {
  plan: (target: RestoreTarget) =>
    api.get<RestorePlan>(`${pathOf(target)}/restore-plan`),

  restore: (target: RestoreTarget) =>
    api.post<unknown>(`${pathOf(target)}/restore${restoreQuery(target)}`, {}),
}

/** The target for a blocker, which is what to restore first. */
export function blockerTarget(b: Blocker): RestoreTarget {
  return { kind: b.kind, ref: b.kind === 'record' ? b.id : b.name }
}
