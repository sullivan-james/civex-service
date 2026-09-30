/** Human-readable text for filter trees -- the chips under the search box
 * and the summary line. */

import {
  FILTER_OPERATORS,
  type FilterConditionWire,
  type FilterTreeWire,
} from './filterTree'
import type { FilterableField } from './hierarchy'
import { displayLabel } from './naming'

function isGroup(
  wire: FilterTreeWire,
): wire is { and?: FilterTreeWire[]; or?: FilterTreeWire[] } {
  return 'and' in wire || 'or' in wire
}

function formatValue(value: unknown): string {
  if (Array.isArray(value)) return value.join(', ')
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  return String(value ?? '')
}

/** "Recording · sample rate ≥ 96" -- the owning schema is named unless it is
 * the one being listed. */
export function conditionLabel(
  c: FilterConditionWire,
  fields: FilterableField[],
  listedSchema: string,
): string {
  const field = fields.find(
    (f) =>
      f.name === c.field &&
      (c.schema
        ? f.sourceSchemaName === c.schema
        : f.relation !== 'descendant'),
  )
  const owner = c.schema ?? listedSchema
  const name = field ? displayLabel(field.name, field.label) : c.field
  const prefix = owner === listedSchema ? '' : `${displayLabel(owner)} · `
  if (c.op === 'is_null') return `${prefix}${name} is empty`
  const op = FILTER_OPERATORS.find((o) => o.value === c.op)?.label ?? c.op
  return `${prefix}${name} ${op} ${formatValue(c.value)}`
}

/** A whole tree as one phrase: "(a and b)" for a nested group. */
export function describeTree(
  wire: FilterTreeWire,
  fields: FilterableField[],
  listedSchema: string,
): string {
  if (!isGroup(wire)) return conditionLabel(wire, fields, listedSchema)
  const op = 'and' in wire ? 'and' : 'or'
  const parts = (wire.and ?? wire.or ?? []).map((c) =>
    describeTree(c, fields, listedSchema),
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
