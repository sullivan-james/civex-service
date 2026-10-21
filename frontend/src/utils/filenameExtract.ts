/**
 * A field filled from a file's name: the `from_filename` restriction.
 *
 * Mirrors `civex/domain/filename_extract.py`, which is what the server runs
 * as a record is saved; this copy only gives a live preview (the rule editor
 * and the new-record form) and the hint beside a field. The two must agree:
 * a date or datetime field's pattern is a token format (`YYYY MM DD HH mm
 * SS`, anything else a regular expression, searched for anywhere in the
 * name, year, month and day required); a text or number field's pattern is
 * a regular expression whose first capture group is the value, else the
 * whole match.
 */
import type { Field } from '../api/schemas'
import {
  extractCaptureGroup,
  parseFilenameByTokenFormat,
} from './filenamePattern'

/** Field types a value can be read out of a file name for. */
export const FROM_FILENAME_KINDS = new Set([
  'string',
  'integer',
  'float',
  'date',
  'datetime',
])

/** Kinds whose pattern is a token format rather than a plain regex. */
export const DATE_KINDS = new Set(['date', 'datetime'])

export interface FromFilenameRule {
  /** The `file` or `file_list` field whose file's name is read. */
  field: string
  pattern: string
}

/** The rule on a field's restrictions, or null when it has none. */
export function fromFilenameRule(
  restrictions: Record<string, unknown> | null | undefined,
): FromFilenameRule | null {
  const rule = restrictions?.from_filename
  if (!rule || typeof rule !== 'object') return null
  const { field, pattern } = rule as Record<string, unknown>
  if (typeof field !== 'string' || typeof pattern !== 'string') return null
  if (!field) return null
  return { field, pattern }
}

/** The name of the file in a `file` or `file_list` value (the first file of
 * a list), or null when there is no file. */
export function firstFilename(value: unknown): string | null {
  const one = Array.isArray(value) ? value[0] : value
  if (!one || typeof one !== 'object') return null
  const name = (one as { filename?: unknown }).filename
  return typeof name === 'string' && name ? name : null
}

/** Why `pattern` can't read a `kind`, or null when it can: the server's
 * `compile_pattern`, so a rule refused here is refused there too. */
export function patternProblem(pattern: string, kind: string): string | null {
  if (!FROM_FILENAME_KINDS.has(kind))
    return `a ${kind} field can't be filled from a file name`
  if (!pattern.trim()) return 'the pattern is empty'
  if (DATE_KINDS.has(kind)) {
    const missing = ['YYYY', 'MM', 'DD'].filter((t) => !pattern.includes(t))
    if (missing.length)
      return `a ${kind} pattern needs the tokens ${missing.join(' ')}`
  }
  try {
    // The token format is a regex once its tokens are groups; the tokens
    // themselves are plain letters, so checking the format as written finds
    // the same syntax errors.
    new RegExp(pattern)
  } catch (e) {
    return `not a valid regular expression: ${(e as Error).message}`
  }
  return null
}

export interface ExtractResult {
  /** The value, or null when the pattern doesn't match (the field stays blank). */
  value: unknown
  /** Why the name couldn't give a value of this kind, when it matched. */
  error: string | null
}

function daysIn(year: number, month: number): number {
  return new Date(Date.UTC(year, month, 0)).getUTCDate()
}

/** Whether an ISO date / naive datetime from the token parser names a real
 * moment (the parser only checks digit counts). */
function isRealDate(iso: string): boolean {
  const [date, time] = iso.split('T')
  const [y, m, d] = date.split('-').map(Number)
  if (m < 1 || m > 12 || d < 1 || d > daysIn(y, m)) return false
  if (!time) return true
  const [hh, mm, ss] = time.split(':').map(Number)
  return hh < 24 && mm < 60 && ss < 60
}

/** The value of `kind` that `pattern` reads out of `filename`: the server's
 * `extract`. `value` is null when the pattern doesn't match; `error` is set
 * when it matches but what it captured isn't a `kind`. */
export function extractFromFilename(
  filename: string,
  pattern: string,
  kind: string,
): ExtractResult {
  const problem = patternProblem(pattern, kind)
  if (problem) return { value: null, error: problem }
  if (DATE_KINDS.has(kind)) {
    let iso: string | null
    try {
      iso = parseFilenameByTokenFormat(filename, pattern)
    } catch (e) {
      return { value: null, error: (e as Error).message }
    }
    if (iso === null) return { value: null, error: null }
    if (!isRealDate(iso)) return { value: null, error: `not a ${kind}` }
    return {
      value: kind === 'date' ? iso.slice(0, 10) : iso.slice(0, 19),
      error: null,
    }
  }
  const captured = extractCaptureGroup(filename, pattern)
  if (captured.value === null) return { value: null, error: null }
  if (kind === 'integer') {
    if (!/^[+-]?\d+$/.test(captured.value.trim()))
      return { value: null, error: `'${captured.value}' is not a whole number` }
    return { value: parseInt(captured.value, 10), error: null }
  }
  if (kind === 'float') {
    const n = Number(captured.value.trim())
    if (captured.value.trim() === '' || Number.isNaN(n))
      return { value: null, error: `'${captured.value}' is not a number` }
    return { value: n, error: null }
  }
  return { value: captured.value, error: null }
}

/** What the record form would show for a blank field with a rule, given the
 * record's values so far: the file's name and what it gives, or null when
 * there is no file to read (or the field already has a value). */
export function previewFromFilename(
  field: Field,
  values: Record<string, unknown>,
): { filename: string; result: ExtractResult } | null {
  const rule = fromFilenameRule(field.restrictions)
  if (!rule) return null
  const current = values[field.name]
  if (current !== undefined && current !== null && current !== '') return null
  const filename = firstFilename(values[rule.field])
  if (!filename) return null
  return {
    filename,
    result: extractFromFilename(filename, rule.pattern, field.type),
  }
}
