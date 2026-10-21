/**
 * A field filled from a file's name: the `from_filename` restriction.
 *
 * Mirrors `civex/domain/filename_extract.py`, which is what the server runs
 * as a record is saved; this copy only gives a live preview (the rule editor
 * and the new-record form) and the hint beside a field. The two must agree
 * and are tested against the same table of examples.
 *
 * A rule's `pattern` is one pattern or a list tried in order, first match
 * wins. A pattern takes one of three forms: for a date or datetime a token
 * format (`YYYY MM DD HH mm SS`, anything else a regular expression, year,
 * month and day required) or a regular expression with Python-style named
 * groups for the parts (`(?P<year>\d{4})`, `month`, `day`, `hour`,
 * `minute`, `second`; a pattern that has named groups is read this way); for
 * text and numbers a regular expression whose first capture group is the
 * value, else the whole match. Patterns are searched for anywhere in the
 * name.
 */
import type { Field } from '../api/schemas'

/** Field types a value can be read out of a file name for. */
export const FROM_FILENAME_KINDS = new Set([
  'string',
  'integer',
  'float',
  'date',
  'datetime',
])

/** Kinds whose pattern names the parts of a date. */
export const DATE_KINDS = new Set(['date', 'datetime'])

/** The named groups a date regex may use. */
export const DATE_PARTS = ['year', 'month', 'day', 'hour', 'minute', 'second']
const REQUIRED_TOKENS = ['YYYY', 'MM', 'DD']
const REQUIRED_PARTS = ['year', 'month', 'day']

const TOKEN_RE = /(YYYY|MM|DD|HH|mm|SS)/
const TOKEN_MAP: Record<string, string> = {
  YYYY: '(?<year>\\d{4})',
  MM: '(?<month>\\d{2})',
  DD: '(?<day>\\d{2})',
  HH: '(?<hour>\\d{2})',
  mm: '(?<minute>\\d{2})',
  SS: '(?<second>\\d{2})',
}
const NAMED_GROUP_RE = /\(\?P<(\w+)>/g

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

/** Whether `pattern` is a regular expression with named groups. */
export function isNamed(pattern: string): boolean {
  return /\(\?P<\w+>/.test(pattern)
}

/** Python's `(?P<name>` as JavaScript's `(?<name>`. */
function asJs(pattern: string): string {
  return pattern.replace(NAMED_GROUP_RE, '(?<$1>')
}

/** The token format as a regular expression with named groups. */
function tokenRegex(fmt: string): string {
  return fmt
    .split(TOKEN_RE)
    .map((part) => TOKEN_MAP[part] ?? part)
    .join('')
}

/** The regular expression source for `pattern` read for `kind`, assuming it
 * passed `patternProblem`. */
function regexSource(pattern: string, kind: string): string {
  if (DATE_KINDS.has(kind) && !isNamed(pattern)) return tokenRegex(pattern)
  return asJs(pattern)
}

/** Why `pattern` can't read a `kind`, or null when it can: the server's
 * `compile_pattern`, so a rule refused here is refused there too. */
export function patternProblem(pattern: string, kind: string): string | null {
  if (!FROM_FILENAME_KINDS.has(kind))
    return `a ${kind} field can't be filled from a file name`
  if (!pattern.trim()) return 'the pattern is empty'
  if (DATE_KINDS.has(kind)) {
    if (isNamed(pattern)) {
      const names = new Set(
        [...pattern.matchAll(NAMED_GROUP_RE)].map((m) => m[1]),
      )
      const missing = REQUIRED_PARTS.filter((p) => !names.has(p))
      if (missing.length)
        return `a ${kind} pattern with named groups needs ${missing.join(', ')} (the groups are ${DATE_PARTS.join(' ')})`
      const unknown = [...names].filter((n) => !DATE_PARTS.includes(n)).sort()
      if (unknown.length)
        return `unknown group(s) ${unknown.join(', ')}: a ${kind} pattern's groups are ${DATE_PARTS.join(' ')}`
    } else {
      const missing = REQUIRED_TOKENS.filter((t) => !pattern.includes(t))
      if (missing.length)
        return `a ${kind} pattern needs the tokens ${missing.join(' ')}`
    }
  }
  try {
    new RegExp(regexSource(pattern, kind))
  } catch (e) {
    return `not a valid regular expression: ${(e as Error).message}`
  }
  return null
}

export interface ExtractResult {
  /** The value, or null when no pattern matches (the field stays blank). */
  value: unknown
  /** Why the name couldn't give a value of this kind, when a pattern matched. */
  error: string | null
}

function daysIn(year: number, month: number): number {
  return new Date(Date.UTC(year, month, 0)).getUTCDate()
}

const pad = (n: number, width: number) => String(n).padStart(width, '0')

/** The date the match's groups name, as the server writes it, or null when
 * the numbers don't make a date. */
function dateValue(
  groups: Record<string, string | undefined>,
  kind: string,
): string | null {
  const n = (part: string, fallback: number) =>
    groups[part] ? parseInt(groups[part]!, 10) : fallback
  const year = n('year', 1970)
  const month = n('month', 1)
  const day = n('day', 1)
  const hour = n('hour', 0)
  const minute = n('minute', 0)
  const second = n('second', 0)
  if (month < 1 || month > 12 || day < 1 || day > daysIn(year, month))
    return null
  if (hour > 23 || minute > 59 || second > 59) return null
  const date = `${pad(year, 4)}-${pad(month, 2)}-${pad(day, 2)}`
  if (kind === 'date') return date
  return `${date}T${pad(hour, 2)}:${pad(minute, 2)}:${pad(second, 2)}`
}

/** The value a match gives for `kind`, as the server's `_value_of`. */
function valueOf(m: RegExpExecArray, kind: string): ExtractResult {
  if (DATE_KINDS.has(kind)) {
    const value = dateValue(m.groups ?? {}, kind)
    return value === null
      ? { value: null, error: `'${m[0]}' is not a ${kind}` }
      : { value, error: null }
  }
  const captured = m.length > 1 && m[1] !== undefined ? m[1] : m[0]
  if (kind === 'integer') {
    if (!/^[+-]?\d+$/.test(captured.trim()))
      return { value: null, error: `'${captured}' is not a whole number` }
    return { value: parseInt(captured, 10), error: null }
  }
  if (kind === 'float') {
    const n = Number(captured.trim())
    if (captured.trim() === '' || Number.isNaN(n))
      return { value: null, error: `'${captured}' is not a number` }
    return { value: n, error: null }
  }
  return { value: captured, error: null }
}

/** The value of `kind` that `patterns` (one, or several tried in order, the
 * first that matches deciding) read out of `filename`: the server's
 * `extract`. `value` is null when none matches; `error` is set when the
 * pattern is bad or the match isn't a `kind`. */
export function extractFromFilename(
  filename: string,
  patterns: string | string[],
  kind: string,
): ExtractResult {
  for (const pattern of patternsOf(patterns)) {
    const problem = patternProblem(pattern, kind)
    if (problem) return { value: null, error: problem }
    const m = new RegExp(regexSource(pattern, kind)).exec(filename)
    if (m) return valueOf(m, kind)
  }
  return { value: null, error: null }
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
    result: extractFromFilename(filename, rule.patterns, field.type),
  }
}
