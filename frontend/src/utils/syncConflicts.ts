import type {
  ConflictChange,
  ConflictResolution,
  ConflictTake,
  SyncConflict,
} from '../api/remote'

/** What each button says. Which ones a row has is the server's word
 * (`conflict.takes`); this is only wording. */
const LABELS: Record<string, Partial<Record<ConflictTake, string>>> = {
  conflict: { theirs: 'Keep theirs', mine: 'Use mine', value: 'Edit…' },
  edit_vs_delete: { theirs: 'Keep it', delete: 'Delete it' },
  rejected: { theirs: 'Let it go', retry: 'Send again' },
  not_taken: { theirs: 'OK' },
}

export function takeLabel(kind: string, take: ConflictTake): string {
  return LABELS[kind]?.[take] ?? (take === 'theirs' ? 'Dismiss' : take)
}

/** What a kind of conflict is called when choosing among them. */
const KINDS: Record<string, string> = {
  conflict: 'Clashes',
  rejected: 'Refused',
  edit_vs_delete: 'Deleted there',
  not_taken: 'Not taken',
}

export function kindLabel(kind: string): string {
  return KINDS[kind] ?? kind
}

/** A record's conflicts sit together, then oldest first: the order they are
 * stepped through on the review page and from record to record. */
export function inReviewOrder(list: SyncConflict[]): SyncConflict[] {
  return [...list].sort(
    (a, b) =>
      (a.record_name ?? a.entity_id).localeCompare(
        b.record_name ?? b.entity_id,
      ) || a.created_at.localeCompare(b.created_at),
  )
}

/** Where a record's conflicts are shown on its page. */
export interface ConflictLayout {
  /** A clash, under the field it is about (by field name). */
  clashes: Map<string, SyncConflict[]>
  /** What a refused or colliding change set, under each field it set. */
  attempts: Map<string, { conflict: SyncConflict; change: ConflictChange }[]>
  /** Fields to mark on the page. */
  marked: Set<string>
  /** About the record as a whole: refused changes, edits that met a delete. */
  recordLevel: SyncConflict[]
  /** Clashes whose field is no longer on the record: nothing to put them under. */
  loose: SyncConflict[]
  /** How many there are in all. */
  count: number
}

/** Sort a record's conflicts into the places its page shows them: a clash under
 * its field, a change under each field it set, the rest at the top. */
export function layoutConflicts(
  conflicts: SyncConflict[],
  fields: { id: string; name: string }[],
): ConflictLayout {
  const nameOf = new Map(fields.map((f) => [`data.${f.id}`, f.name]))
  const out: ConflictLayout = {
    clashes: new Map(),
    attempts: new Map(),
    marked: new Set(),
    recordLevel: [],
    loose: [],
    count: conflicts.length,
  }
  const push = <T>(m: Map<string, T[]>, key: string, v: T) =>
    m.set(key, [...(m.get(key) ?? []), v])
  for (const c of conflicts) {
    if (c.kind === 'conflict') {
      const name = c.field ? nameOf.get(c.field) : undefined
      if (name === undefined) out.loose.push(c)
      else {
        push(out.clashes, name, c)
        out.marked.add(name)
      }
      continue
    }
    out.recordLevel.push(c)
    for (const change of c.changes) {
      if (!fields.some((f) => f.name === change.field_name)) continue
      push(out.attempts, change.field_name, { conflict: c, change })
      out.marked.add(change.field_name)
    }
  }
  return out
}

/** What a change that was not applied says, in a sentence: what was tried and
 * why it did not go in. (Only refused changes and edits against a delete: a
 * clash is shown as the two values.) */
export function describeAttempt(
  c: SyncConflict,
  when: (iso: string) => string,
): string {
  const who = c.theirs_actor
    ? `${c.theirs_actor}${c.theirs_at ? ` on ${when(c.theirs_at)}` : ''}`
    : null
  if (c.kind === 'not_taken')
    return `Your change was not taken, and this is back as the server has it. ${c.message ?? ''} Make the change again if you still want it.`.trim()
  if (c.kind === 'rejected') {
    const why = (c.message ?? '').replace(/\.?$/, '.')
    if (c.attempted === 'delete')
      return `Deleting this record was refused. ${why}`.trim()
    const what =
      c.attempted === 'create'
        ? "This record isn't on the server yet."
        : 'Your change to this record was refused.'
    return `${what} ${why} Fix it below: saving sends it again.`.trim()
  }
  if (c.attempted === 'delete')
    return `It was edited elsewhere${who ? ` (${who})` : ''} after you last saw it, so your delete was not applied.`
  return `It was deleted elsewhere${who ? ` (${who})` : ''}, and you edited it. It has been kept here.`
}

/** How a settled one is described. Besides what a person chose: `sent` (a
 * refused record went in once fixed) and `replaced` (a later attempt took its
 * place, so it is not shown). */
export function settledLabel(take: ConflictResolution | null): string {
  switch (take) {
    case 'sent':
      return 'Went in'
    case 'replaced':
      return 'Replaced by a later attempt'
    case 'theirs':
      return 'Kept theirs'
    case 'mine':
      return 'Used yours'
    case 'edited':
    case 'value':
      return 'Edited'
    case 'delete':
      return 'Deleted'
    case 'retry':
      return 'Sent again'
    default:
      return 'Settled'
  }
}
