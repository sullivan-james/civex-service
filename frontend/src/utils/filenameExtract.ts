/**
 * A field filled from a file's name: reading the `from_filename` rule off a
 * field. The patterns themselves are only ever run by the server
 * (`civex/domain/filename_extract.py`); the editor's live preview asks it
 * through `schemasApi.previewFromFilename`.
 */

/** Kinds whose pattern names the parts of a date. */
export const DATE_KINDS = new Set(['date', 'datetime'])

export interface FromFilenameRule {
  /** The `file` or `file_list` field whose file's name is read. */
  field: string
  /** The patterns, tried in order. */
  patterns: string[]
}

/** A rule's `pattern` as the patterns to try: one string, or a list. */
export function patternsOf(value: unknown): string[] {
  if (typeof value === 'string') return [value]
  if (Array.isArray(value))
    return value.filter((v): v is string => typeof v === 'string')
  return []
}

/** The rule on a field's restrictions, or null when it has none. */
export function fromFilenameRule(
  restrictions: Record<string, unknown> | null | undefined,
): FromFilenameRule | null {
  const rule = restrictions?.from_filename
  if (!rule || typeof rule !== 'object') return null
  const { field, pattern } = rule as Record<string, unknown>
  if (typeof field !== 'string' || !field) return null
  if (typeof pattern !== 'string' && !Array.isArray(pattern)) return null
  return { field, patterns: patternsOf(pattern) }
}

/** The name of the file in a `file` or `file_list` value (the first file of
 * a list), or null when there is no file. */
export function firstFilename(value: unknown): string | null {
  const one = Array.isArray(value) ? value[0] : value
  if (!one || typeof one !== 'object') return null
  const name = (one as { filename?: unknown }).filename
  return typeof name === 'string' && name ? name : null
}
