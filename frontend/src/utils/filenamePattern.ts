/**
 * Filename pattern extraction — the frontend counterpart to the token-based
 * date format parsed server-side by `_parse_by_format` in
 * `civex/plugins/builtins/extract_from_filename.py`, and the plain-regex
 * capture-group extraction in `civex/plugins/builtins/match_files_to_records.py`.
 *
 * Keeping this logic in JS (rather than round-tripping every keystroke to
 * the server) is what makes a live preview against real filenames possible.
 */

export const FILENAME_FORMAT_TOKENS_HELP = 'YYYY MM DD HH mm SS'

const TOKEN_RE = /(YYYY|MM|DD|HH|mm|SS)/
const TOKEN_MAP: Record<string, { re: string; key: string }> = {
  YYYY: { re: '(\\d{4})', key: 'year' },
  MM: { re: '(\\d{2})', key: 'month' },
  DD: { re: '(\\d{2})', key: 'day' },
  HH: { re: '(\\d{2})', key: 'hour' },
  mm: { re: '(\\d{2})', key: 'minute' },
  SS: { re: '(\\d{2})', key: 'second' },
}

/**
 * Parse `str` according to a token format like 'YYYYMMDD-HHmmSS' — mirrors
 * `_parse_by_format` in `civex.extract_from_filename` exactly, down to
 * leaving non-token characters as raw (unescaped) regex, so e.g.
 * 'YYYYMMDD[-_]HHmmSS' matches both dashes and underscores. Returns an ISO
 * date (`YYYY-MM-DD`) or naive datetime (`YYYY-MM-DDTHH:mm:SS`) string, or
 * null if the format doesn't match or lacks a year/month/day.
 */
export function parseFilenameByTokenFormat(
  str: string,
  fmt: string,
): string | null {
  const groups: string[] = []
  let pattern = ''
  for (const part of fmt.split(TOKEN_RE)) {
    const token = TOKEN_MAP[part]
    if (token) {
      pattern += token.re
      groups.push(token.key)
    } else {
      pattern += part
    }
  }
  const m = new RegExp(pattern).exec(str)
  if (!m) return null
  const v: Record<string, string> = {}
  groups.forEach((k, idx) => {
    v[k] = m[idx + 1]
  })
  const { year, month, day, hour, minute = '00', second = '00' } = v
  if (!year || !month || !day) return null
  return hour !== undefined
    ? `${year}-${month}-${day}T${hour}:${minute}:${second}`
    : `${year}-${month}-${day}`
}

export interface CaptureResult {
  value: string | null
  error: string | null
}

/**
 * Apply `pattern` to `filename` and return the first capture group (or the
 * whole match if the pattern has no group) — mirrors
 * `civex.match_files_to_records`'s `re.search(pattern, filename)` /
 * `m.group(1)` and `civex.extract_from_filename`'s equivalent.
 */
export function extractCaptureGroup(
  filename: string,
  pattern: string,
): CaptureResult {
  if (!pattern) return { value: null, error: null }
  let m: RegExpExecArray | null
  try {
    m = new RegExp(pattern).exec(filename)
  } catch (e) {
    return { value: null, error: `Invalid regex: ${(e as Error).message}` }
  }
  if (!m) return { value: null, error: 'No match in filename' }
  return { value: m[1] ?? m[0], error: null }
}

/**
 * Normalise a numeric capture the same way `civex.match_files_to_records`
 * does — "01" -> "1" — so a zero-padded filename key matches an integer
 * field. Non-integer-looking strings pass through unchanged (mirrors
 * Python's `int(key_value)` raising and being caught).
 */
export function normalizeNumericKey(raw: string): string {
  const trimmed = raw.trim()
  return /^-?\d+$/.test(trimmed) ? String(parseInt(trimmed, 10)) : raw
}
