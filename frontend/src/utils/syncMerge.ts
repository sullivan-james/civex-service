import type { ConflictTake, SyncConflict } from '../api/remote'
import { inReviewOrder } from './syncConflicts'

/** One field in the merge view: the two sides, what each is called, and whether
 * it has been settled. */
export interface MergeRow {
  key: string
  /** The field on the record now; null when it has been removed. */
  fieldName: string | null
  label: string
  dtype: string | null
  conflict: SyncConflict
  /** The other side's (a clash) or the value before the change (an attempt). */
  left: unknown
  /** This device's value. */
  right: unknown
  /** What it was before either side changed it (a clash). */
  base: unknown
  /** How it was settled, once it has been. */
  settled: ConflictTake | null
}

/** A group of rows that share a header and a way of settling. */
export type MergeSection =
  | { kind: 'clashes'; rows: MergeRow[] }
  | { kind: 'attempt'; conflict: SyncConflict; rows: MergeRow[] }

export interface MergeModel {
  sections: MergeSection[]
  /** Still to settle. */
  open: number
  /** How many conflicts there are, settled this visit or not. */
  total: number
}

/** A record's conflicts as a merge view lays them out: all its clashes together,
 * then each refused change or edit-against-a-delete with the fields it set. */
export function buildMerge(
  conflicts: SyncConflict[],
  fields: { id: string; name: string }[],
): MergeModel {
  const nameOf = new Map(fields.map((f) => [`data.${f.id}`, f.name]))
  const settled = (c: SyncConflict): ConflictTake | null =>
    c.status === 'resolved' ? c.resolution : null
  const clashes: MergeRow[] = []
  const sections: MergeSection[] = []
  for (const c of inReviewOrder(conflicts)) {
    if (c.kind === 'conflict') {
      clashes.push({
        key: c.id,
        fieldName: (c.field && nameOf.get(c.field)) || null,
        label: c.field_label ?? 'A field that has since been removed',
        dtype: c.dtype,
        conflict: c,
        left: c.theirs,
        right: c.yours,
        base: c.base,
        settled: settled(c),
      })
      continue
    }
    sections.push({
      kind: 'attempt',
      conflict: c,
      rows: c.changes.map((change) => ({
        key: `${c.id}:${change.field_id}`,
        fieldName: fields.some((f) => f.name === change.field_name)
          ? change.field_name
          : null,
        label: change.field_label,
        dtype: change.dtype,
        conflict: c,
        left: change.before,
        right: change.after,
        base: undefined,
        settled: settled(c),
      })),
    })
  }
  if (clashes.length) sections.unshift({ kind: 'clashes', rows: clashes })
  return {
    sections,
    open: conflicts.filter((c) => c.status === 'open').length,
    total: conflicts.length,
  }
}
