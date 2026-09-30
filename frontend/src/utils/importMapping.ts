import type { Field } from '../api/schemas'
import type { FieldType } from './fieldTypes'

function normalizeKey(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, '')
}

/**
 * Best-effort column -> existing field name mapping, matched by normalized
 * name or label. Unmatched columns map to `null` (caller offers "create new
 * field" or "skip").
 */
export function suggestFieldMapping(
  columns: string[],
  fields: Field[],
): Record<string, string | null> {
  const used = new Set<string>()
  const result: Record<string, string | null> = {}
  for (const col of columns) {
    const normCol = normalizeKey(col)
    const match = fields.find(
      (f) =>
        !used.has(f.name) &&
        (normalizeKey(f.name) === normCol ||
          (f.label && normalizeKey(f.label) === normCol)),
    )
    if (match) {
      result[col] = match.name
      used.add(match.name)
    } else {
      result[col] = null
    }
  }
  return result
}

// The subset of FieldType (`utils/fieldTypes.ts`) inferable from raw text
// values alone -- no file/reference/enum/etc., which need more than a
// sample of strings to justify. `Extract` against the canonical union so a
// type renamed there is a compile error here instead of silent drift.
export type InferredFieldType = Extract<
  FieldType,
  'integer' | 'float' | 'boolean' | 'date' | 'datetime' | 'string'
>

/** Infer a schema field dtype from sample column values. Falls back to
 * `string` — the always-safe choice — whenever the sample is empty or mixed. */
export function inferColumnType(values: string[]): InferredFieldType {
  const nonEmpty = values.map((v) => v.trim()).filter((v) => v !== '')
  if (nonEmpty.length === 0) return 'string'
  if (nonEmpty.every((v) => /^-?\d+$/.test(v))) return 'integer'
  if (nonEmpty.every((v) => /^-?\d+(\.\d+)?$/.test(v))) return 'float'
  if (nonEmpty.every((v) => /^(true|false)$/i.test(v))) return 'boolean'
  if (nonEmpty.every((v) => /^\d{4}-\d{2}-\d{2}$/.test(v))) return 'date'
  if (nonEmpty.every((v) => !isNaN(Date.parse(v)))) return 'datetime'
  return 'string'
}
