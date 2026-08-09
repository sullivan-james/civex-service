import { ApiError } from '../api/client'
import { formatBytes } from './restrictions'

export interface ParsedValidationError {
  /** Plain-language message per field name that caused it. */
  fieldErrors: Record<string, string>
  /** Plain-language summary — the first field error, or a general-purpose
   * message when more than one field is implicated (e.g. several missing
   * required fields). */
  message: string
  /** The raw backend `detail` string, kept for support purposes. Never shown
   * as the primary message. */
  technical: string
}

// Mirrors the message shapes `_check_restrictions()` in record_service.py
// raises — the single source of truth for what a restriction violation looks
// like on the wire. Field name and rest-of-message are split first; only the
// rest is pattern-matched here since the field name is handled separately.
const FIELD_PREFIX_RE = /^Field '([^']+)':\s*(.*)$/s
const MISSING_REQUIRED_RE = /^Missing required fields:\s*(.+)$/

/** "2020-01-01" -> "1 January 2020"; "2020-01-01T09:00:00+00:00" -> "1 January 2020, 09:00". */
function formatDateLike(raw: string): string {
  const hasTime = raw.includes('T')
  const d = new Date(hasTime ? raw : `${raw}T00:00:00Z`)
  if (isNaN(d.getTime())) return raw
  return d.toLocaleString('en-GB', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    ...(hasTime ? { hour: '2-digit', minute: '2-digit' } : {}),
    timeZone: 'UTC',
  })
}

/** Translate the tail of a `Field '<name>': <detail>` message into plain
 * language. Falls back to the raw text for any shape not recognised here, so
 * an unmapped backend message still reaches the user instead of vanishing. */
function describeFieldDetail(detail: string): string {
  let m: RegExpExecArray | null
  if ((m = /^.+ is below minimum \(([^)]+)\)$/.exec(detail))) {
    return `Must be at least ${m[1]}.`
  }
  if ((m = /^.+ exceeds maximum \(([^)]+)\)$/.exec(detail))) {
    return `Must be at most ${m[1]}.`
  }
  if ((m = /^.+ is before minimum \(([^)]+)\)$/.exec(detail))) {
    return `Must be on or after ${formatDateLike(m[1])}.`
  }
  if ((m = /^.+ is after maximum \(([^)]+)\)$/.exec(detail))) {
    return `Must be on or before ${formatDateLike(m[1])}.`
  }
  if ((m = /^'.*' must be one of: (.+)$/.exec(detail))) {
    return `Must be one of: ${m[1]}.`
  }
  if ((m = /^value length (\d+) exceeds max_length (\d+)$/.exec(detail))) {
    return `Must be ${m[2]} characters or fewer (currently ${m[1]}).`
  }
  if (
    (m = /^'(.+)' type '\.[^']*' not allowed — accepted: (.+)$/.exec(detail))
  ) {
    return `'${m[1]}' isn't an accepted file type. Allowed: ${m[2]}.`
  }
  if ((m = /^file size (\d+) bytes exceeds max_size (\d+)$/.exec(detail))) {
    return `File is too large (${formatBytes(Number(m[1]))}). Maximum is ${formatBytes(Number(m[2]))}.`
  }
  if (
    /^'.*' is not a valid URL \(must start with http:\/\/ or https:\/\/\)$/.test(
      detail,
    )
  ) {
    return 'Must be a full URL starting with http:// or https://.'
  }
  return detail
}

/** Parse a record validation failure into field-level, plain-language
 * errors. Returns null for anything that isn't a field-attributable
 * `ValidationError` (e.g. a 404, or a schema-level error) — callers should
 * fall back to `errorMessage()` in that case. */
export function parseValidationError(e: unknown): ParsedValidationError | null {
  if (!(e instanceof ApiError) || typeof e.detail !== 'string') return null
  const detail = e.detail

  const fieldMatch = FIELD_PREFIX_RE.exec(detail)
  if (fieldMatch) {
    const [, field, rest] = fieldMatch
    const message = describeFieldDetail(rest)
    return { fieldErrors: { [field]: message }, message, technical: detail }
  }

  const missingMatch = MISSING_REQUIRED_RE.exec(detail)
  if (missingMatch) {
    const names = missingMatch[1]
      .split(',')
      .map((n) => n.trim())
      .filter(Boolean)
    const fieldErrors = Object.fromEntries(
      names.map((n) => [n, 'This field is required.']),
    )
    const message =
      names.length === 1
        ? `'${names[0]}' is required.`
        : `Fill in the required fields: ${names.join(', ')}.`
    return { fieldErrors, message, technical: detail }
  }

  return null
}

export interface FieldErrorInfo {
  /** Plain-language error per field name — pass to that field's `<Field error>`. */
  fieldErrors: Record<string, string>
  /** Set when the error isn't attributable to a known field — render at form level. */
  generalMessage: string | null
  /** Raw backend detail, offered behind a "technical details" disclosure. */
  technical: string | null
}

/** `errorMessage()`'s field-aware counterpart: splits a record validation
 * error into per-field messages (for known field names) plus whatever's left
 * over for a form-level fallback, so a bad restriction lands next to the
 * field that violated it instead of only in a banner. */
export function fieldErrorInfo(
  error: unknown,
  fieldNames: string[],
  errorMessage: (e: unknown) => string,
): FieldErrorInfo {
  if (!error) return { fieldErrors: {}, generalMessage: null, technical: null }
  const parsed = parseValidationError(error)
  if (!parsed) {
    return {
      fieldErrors: {},
      generalMessage: errorMessage(error),
      technical: null,
    }
  }
  const known = new Set(fieldNames)
  const unattributed = Object.keys(parsed.fieldErrors).filter(
    (f) => !known.has(f),
  )
  return {
    fieldErrors: parsed.fieldErrors,
    generalMessage: unattributed.length ? parsed.message : null,
    technical: parsed.technical,
  }
}
