import type { RunFilterField } from '../api/workflows'
import type { FilterableField } from './hierarchy'
import type { FilterConditionWire, FilterTreeWire } from './filterTree'
import { topLevelTerms } from './filterLabels'
import { RUN_LIST, allOf, runFilterFields } from './runFilter'

/** What the filter chips call the thing being listed. History's fields are the
 * run fields' shape, so it is filtered with the same controls, and the same
 * name stands in for a schema. */
export const AUDIT_LIST = RUN_LIST

/** The history fields as the filter builder's fields. `choices` fills the ones
 * the server can't list itself: the collections that exist. */
export function auditFilterFields(
  fields: RunFilterField[] | undefined,
  choices: Record<string, string[]>,
): FilterableField[] {
  return runFilterFields(fields, choices)
}

const cond = (
  field: string,
  op: FilterConditionWire['op'],
  value: unknown,
): FilterConditionWire => ({ field, op, value })

/** Everything that happened to a record and beneath it, deleted or not. */
export const underRecord = (id: string): FilterTreeWire =>
  cond('under', 'eq', id)

/** Everything that happened in a collection, to records since deleted too. */
export const inCollection = (name: string): FilterTreeWire =>
  cond('collection', 'eq', name)

/** What "Deleted" means: the deletion itself, of something that is deleted now
 * (so it can still be restored). Two conditions, always together. */
const DELETED_TERMS: FilterTreeWire[] = [
  cond('now', 'eq', 'deleted'),
  cond('change', 'eq', 'delete'),
]

const same = (a: FilterTreeWire, b: FilterTreeWire) =>
  JSON.stringify(a) === JSON.stringify(b)

/** Is the filter showing what is deleted? */
export function isDeletedView(filter: FilterTreeWire | null): boolean {
  const terms = topLevelTerms(filter)
  return DELETED_TERMS.every((d) => terms.some((t) => same(t, d)))
}

/** The filter with "Deleted" added, or taken off if it is already on. */
export function toggleDeleted(
  filter: FilterTreeWire | null,
): FilterTreeWire | null {
  const terms = topLevelTerms(filter)
  if (isDeletedView(filter))
    return allOf(...terms.filter((t) => !DELETED_TERMS.some((d) => same(t, d))))
  return allOf(...terms, ...DELETED_TERMS)
}

/** The filter a person sees and edits, with the page's own scope kept apart:
 * a record's history is always under that record, whatever they add. */
export function withScope(
  scope: FilterTreeWire | null | undefined,
  filter: FilterTreeWire | null,
): FilterTreeWire | null {
  return allOf(...[scope, filter].filter((t): t is FilterTreeWire => !!t))
}

/** Where to see what happened to a record, whether or not it still exists: its
 * history, with the deletion (and Restore, if it is only deleted) in it. */
export function recordHistoryHref(id: string): string {
  return `/activity?activity.filter=${encodeURIComponent(JSON.stringify(underRecord(id)))}`
}
