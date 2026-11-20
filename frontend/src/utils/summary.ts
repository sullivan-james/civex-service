/**
 * The explorer's Summary: which groupings and measures a person chose, held
 * in the address as the server writes them (`sum.by=site.region,taken:month`,
 * `sum.m=count,mean:depth`; see civex/domain/summary.py), and which of the
 * listed kind's fields can be grouped by or measured (from the field types'
 * `grouping` and `measures`, the one table).
 */

import type { FieldTypeDescriptor } from '../api/schemas'
import type { FilterableField } from './hierarchy'
import type { FilterTreeWire } from './filterTree'

/** A comma-separated address value as a list (empty: none). */
export function splitKeys(raw: string | null | undefined): string[] {
  return (raw ?? '')
    .split(',')
    .map((k) => k.trim())
    .filter(Boolean)
}

/** A field as a summary names it: its own name, or `kind.name` for a field
 * of a kind above the one listed. */
export function fieldKey(f: FilterableField): string {
  return f.relation === 'self' ? f.name : `${f.sourceSchemaName}.${f.name}`
}

/** `site.region:month` -> the field part and how it is grouped. */
export function splitGroupKey(key: string): { field: string; how: string } {
  const at = key.indexOf(':')
  return at < 0
    ? { field: key, how: '' }
    : { field: key.slice(0, at), how: key.slice(at + 1) }
}

/** The fields a summary of the listed kind can use: its own and those of the
 * kinds above it (a record has many of a kind beneath it, so those can't). */
export function summaryFields(
  fields: FilterableField[],
  types: FieldTypeDescriptor[],
): { field: FilterableField; type: FieldTypeDescriptor }[] {
  const byType = new Map(types.map((t) => [t.type, t]))
  return fields.flatMap((field) => {
    const type = byType.get(field.type)
    return type && field.relation !== 'descendant' ? [{ field, type }] : []
  })
}

/** A group's condition added to the explorer's filter: what drilling into it
 * lists. */
export function withCondition(
  filter: FilterTreeWire | null,
  where: FilterTreeWire,
): FilterTreeWire {
  return filter ? { and: [filter, where] } : where
}

/** A cell of a summary as a person reads it. */
export function formatSummaryValue(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'number')
    return value.toLocaleString(undefined, { maximumFractionDigits: 4 })
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  return String(value)
}

/** Sort rows by a column (a group's value or a measure), blanks last. */
export function compareSummaryCells(a: unknown, b: unknown): number {
  if (a === b) return 0
  if (a === null || a === undefined) return 1
  if (b === null || b === undefined) return -1
  if (typeof a === 'number' && typeof b === 'number') return a - b
  return String(a).localeCompare(String(b), undefined, { numeric: true })
}
