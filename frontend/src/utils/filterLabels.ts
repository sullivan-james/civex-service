/** Human-readable text for filter trees -- the chips under the search box
 * and the summary line. */

import {
  FILTER_OPERATORS,
  type FilterConditionWire,
  type FilterTreeWire,
} from './filterTree'
import { findFilterField, type FilterableField } from './hierarchy'
import { displayLabel } from './naming'

function isGroup(
  wire: FilterTreeWire,
): wire is { and?: FilterTreeWire[]; or?: FilterTreeWire[] } {
  return 'and' in wire || 'or' in wire
}

/** Record id -> display name, for reference values. */
export type RecordLabels = Readonly<Record<string, string>>

function formatValue(
  value: unknown,
  recordLabel?: (id: string) => string,
): string {
  if (Array.isArray(value))
    return value.map((v) => formatValue(v, recordLabel)).join(', ')
  if (recordLabel && typeof value === 'string') return recordLabel(value)
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  return String(value ?? '')
}

/** "Recording · sample rate ≥ 96" -- the owning schema is named unless it is
 * the one being listed. */
export function conditionLabel(
  c: FilterConditionWire,
  fields: FilterableField[],
  listedSchema: string,
  labels?: RecordLabels,
): string {
  const field = findFilterField(fields, c)
  const owner = c.schema ?? listedSchema
  const name = field ? displayLabel(field.name, field.label) : c.field
  const prefix = owner === listedSchema ? '' : `${displayLabel(owner)} · `
  if (c.op === 'is_null') return `${prefix}${name} is empty`
  const op = FILTER_OPERATORS.find((o) => o.value === c.op)?.label ?? c.op
  // Only a reference's value is a record id. A name not fetched yet (or of a
  // record since deleted) falls back to the id's short form.
  const isReference =
    field?.type === 'reference' || field?.type === 'reference_list'
  const value = formatValue(
    c.value,
    isReference ? (id) => labels?.[id] ?? id.slice(0, 8) : undefined,
  )
  return `${prefix}${name} ${op} ${value}`
}

/** A whole tree as one phrase: "(a and b)" for a nested group. */
export function describeTree(
  wire: FilterTreeWire,
  fields: FilterableField[],
  listedSchema: string,
  labels?: RecordLabels,
): string {
  if (!isGroup(wire)) return conditionLabel(wire, fields, listedSchema, labels)
  const op = 'and' in wire ? 'and' : 'or'
  const parts = (wire.and ?? wire.or ?? []).map((c) =>
    describeTree(c, fields, listedSchema, labels),
  )
  return parts.length === 1 ? parts[0] : `(${parts.join(` ${op} `)})`
}

/** The tree's top-level terms, one chip each: the children of an AND group,
 * or the whole tree when it is a lone condition or an OR group. */
export function topLevelTerms(wire: FilterTreeWire | null): FilterTreeWire[] {
  if (!wire) return []
  if (isGroup(wire) && 'and' in wire) return wire.and ?? []
  return [wire]
}

/** The tree without its `index`-th top-level term. */
export function withoutTerm(
  wire: FilterTreeWire | null,
  index: number,
): FilterTreeWire | null {
  const rest = topLevelTerms(wire).filter((_, i) => i !== index)
  if (rest.length === 0) return null
  return rest.length === 1 ? rest[0] : { and: rest }
}

/** Every record id a tree's reference conditions mention, so their names can
 * be fetched once for the chips. */
export function referenceIdsIn(
  wire: FilterTreeWire | null,
  fields: FilterableField[],
): string[] {
  const ids = new Set<string>()
  function walk(node: FilterTreeWire) {
    if (isGroup(node)) {
      for (const child of node.and ?? node.or ?? []) walk(child)
      return
    }
    const type = findFilterField(fields, node)?.type
    if (type !== 'reference' && type !== 'reference_list') return
    for (const v of Array.isArray(node.value) ? node.value : [node.value])
      if (typeof v === 'string' && v) ids.add(v)
  }
  if (wire) walk(wire)
  return [...ids]
}
