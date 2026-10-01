import type { Field } from '../api/schemas'
import { parseLocation } from './geo'

/** True for the values the record form treats as "not set" -- omitted from
 * payloads rather than sent as empty strings/nulls. An empty list counts as
 * empty too (a cleared `file_list` / `reference_list` / `tags`). */
export function isEmptyValue(value: unknown): boolean {
  return (
    value === '' ||
    value === undefined ||
    value === null ||
    (Array.isArray(value) && value.length === 0)
  )
}

/** Form-control value -> API value. Number inputs hand back strings; empty
 * values become `undefined` so callers can omit the key. */
export function coerceFieldValue(value: unknown, type: string): unknown {
  if (isEmptyValue(value)) return undefined
  if (type === 'integer') return parseInt(value as string, 10)
  if (type === 'float') {
    // Number(), not parseFloat: "1024 ft" must not quietly become 1024.
    const n = Number(value)
    return Number.isNaN(n) ? value : n
  }
  if (type === 'geo' && typeof value === 'string')
    return parseLocation(value) ?? value
  return value
}

/** Coerce a whole set of form values into a create/update payload, leaving
 * out unset fields. */
export function buildRecordData(
  fields: Pick<Field, 'name' | 'type'>[],
  values: Record<string, unknown>,
): Record<string, unknown> {
  const data: Record<string, unknown> = {}
  for (const field of fields) {
    const coerced = coerceFieldValue(values[field.name], field.type)
    if (coerced !== undefined) data[field.name] = coerced
  }
  return data
}

/** `PATCH /records/{id}` *replaces* a record's data rather than merging, so
 * changing one field means sending every other field back with it. Returns
 * `data` with `fieldName` set to `value` (already coerced), or removed when
 * `value` is undefined. */
export function withFieldValue(
  data: Record<string, unknown>,
  fieldName: string,
  value: unknown,
): Record<string, unknown> {
  const next = { ...data }
  if (value === undefined) delete next[fieldName]
  else next[fieldName] = value
  return next
}

/** Structural equality for field values (scalars, FileRef dicts, lists). */
export function sameValue(a: unknown, b: unknown): boolean {
  if (isEmptyValue(a) && isEmptyValue(b)) return true
  return JSON.stringify(a) === JSON.stringify(b)
}
