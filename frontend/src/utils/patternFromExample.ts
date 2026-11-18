/**
 * Writing a file-name pattern from an example: the person marks the part of
 * one name they mean, and this says the pattern for it. It only *writes*
 * patterns; what a pattern makes of a name is the server's to say
 * (`POST /schemas/from-filename/preview`, the one implementation, in
 * `civex/domain/filename_extract.py`). Every pattern written here is valid in
 * both JavaScript and Python `re` (no lookbehind, no JS-only syntax).
 */

import {
  normalizeNumericKey,
  parseFilenameByTokenFormat,
} from './filenamePattern'

type CharClass = 'digit' | 'letter' | 'alnum' | 'other'

const PREFIX_MAX = 20

const isDigit = (c: string) => c >= '0' && c <= '9'
const isLetter = (c: string) => /^[A-Za-z]$/.test(c)
const isAlnum = (c: string) => isDigit(c) || isLetter(c)

/** `text` with every character that means something in a regex escaped, the
 * same way for JavaScript and Python. A dash is left alone: outside a set it
 * is a plain character in both. */
export function escapeRegex(text: string): string {
  return text.replace(/[\\^$.|?*+()[\]{}]/g, '\\$&')
}

function classOf(text: string): CharClass {
  const chars = [...text]
  if (chars.every(isDigit)) return 'digit'
  if (chars.every(isLetter)) return 'letter'
  if (chars.every(isAlnum)) return 'alnum'
  return 'other'
}

function inClass(c: string, cls: CharClass): boolean {
  if (cls === 'digit') return isDigit(c)
  if (cls === 'letter') return isLetter(c)
  if (cls === 'alnum') return isAlnum(c)
  return false
}

const CLASS_RE: Record<Exclude<CharClass, 'other'>, string> = {
  digit: '[0-9]',
  letter: '[A-Za-z]',
  alnum: '[A-Za-z0-9]',
}

/** The text just before the marked part that pins it down: the run of
 * characters right before it that can't belong to it (`sel_` before `07`),
 * at most `PREFIX_MAX` long. With no such run, the whole start of the name,
 * anchored at its beginning. */
function anchorBefore(before: string, cls: CharClass): string {
  let i = before.length
  const outside =
    cls === 'other'
      ? (c: string) => !isAlnum(c)
      : (c: string) => !inClass(c, cls)
  while (i > 0 && outside(before[i - 1]) && before.length - i < PREFIX_MAX) i--
  const run = before.slice(i)
  if (run) return escapeRegex(run)
  return `^${escapeRegex(before)}`
}

/**
 * A regex with one capture group that takes, from names like `name`, the part
 * `name.slice(start, end)`: digits as digits (`sel_([0-9]+)`), letters as
 * letters, a mix as either, anything else up to the text that follows it.
 */
export function keyPattern(name: string, start: number, end: number): string {
  const marked = name.slice(start, end)
  if (!marked) return ''
  const before = name.slice(0, start)
  const after = name.slice(end)
  const cls = classOf(marked)
  const prefix = anchorBefore(before, cls)
  if (cls === 'other') {
    // Lazy, so it needs the text after it to know where to stop.
    let i = 0
    while (i < after.length && !isAlnum(after[i])) i++
    const next = after ? escapeRegex(i > 0 ? after.slice(0, i) : after[0]) : '$'
    return `${prefix}(.+?)${next}`
  }
  const runsOn = after.length > 0 && inClass(after[0], cls)
  const count = runsOn ? `{${marked.length}}` : '+'
  return `${prefix}(${CLASS_RE[cls]}${count})`
}

// ── Dates ────────────────────────────────────────────────────────────────

type Piece = { digits: string } | { sep: string }

function pieces(text: string): Piece[] {
  const out: Piece[] = []
  for (const m of text.matchAll(/[0-9]+|[^0-9]+/g)) {
    out.push(isDigit(m[0][0]) ? { digits: m[0] } : { sep: m[0] })
  }
  return out
}

/** The ways a run of digits splits into date and time groups. */
function splits(length: number): number[][] {
  switch (length) {
    case 2:
      return [[2]]
    case 4:
      return [[4], [2, 2]]
    case 6:
      return [[2, 2, 2]]
    case 8:
      return [
        [4, 2, 2],
        [2, 2, 4],
      ]
    case 10:
      return [[4, 2, 2, 2]]
    case 12:
      return [[4, 2, 2, 2, 2]]
    case 14:
      return [[4, 2, 2, 2, 2, 2]]
    default:
      return []
  }
}

const DATE_ORDERS: { tokens: string[]; note: string }[] = [
  { tokens: ['YYYY', 'MM', 'DD'], note: 'year first' },
  { tokens: ['DD', 'MM', 'YYYY'], note: 'day first' },
  { tokens: ['MM', 'DD', 'YYYY'], note: 'month first' },
]
const TIME_TOKENS = ['HH', 'mm', 'SS']

const LIMITS: Record<string, [number, number]> = {
  MM: [1, 12],
  DD: [1, 31],
  HH: [0, 23],
  mm: [0, 59],
  SS: [0, 59],
}

function separatorRegex(sep: string): string {
  return [...sep]
    .map((c) => (c === '-' || c === '_' ? '[-_]' : escapeRegex(c)))
    .join('')
}

type Group = { len: number; text: string; sepBefore: string }

function product(choices: number[][][]): number[][][] {
  return choices.reduce<number[][][]>(
    (acc, options) => acc.flatMap((done) => options.map((o) => [...done, o])),
    [[]],
  )
}

/**
 * Token formats (`YYYYMMDD[-_]HHmmSS`) that read the marked part of `name` as
 * a date, most likely first, and only those that give a real date for this
 * example (a month of 1 to 12, and so on). A `-` or `_` between parts is
 * written `[-_]` so names that use either are read alike. For a `date` the
 * time is left out. Empty when the marked part isn't a date.
 */
export function dateFormats(
  name: string,
  start: number,
  end: number,
  kind: 'date' | 'datetime',
): string[] {
  const parts = pieces(name.slice(start, end))
  // Separators at the ends of the marking are not part of the date.
  while (parts.length && 'sep' in parts[0]) parts.shift()
  while (parts.length && 'sep' in parts[parts.length - 1]) parts.pop()
  const runs: { digits: string; sepBefore: string }[] = []
  let sep = ''
  for (const p of parts) {
    if ('sep' in p) sep = p.sep
    else {
      runs.push({ digits: p.digits, sepBefore: runs.length ? sep : '' })
      sep = ''
    }
  }
  if (runs.length === 0) return []
  const options = runs.map((r) => splits(r.digits.length))
  if (options.some((o) => o.length === 0)) return []
  const found: string[] = []
  for (const combo of product(options)) {
    const groups: Group[] = []
    combo.forEach((lens, r) => {
      let at = 0
      lens.forEach((len, k) => {
        groups.push({
          len,
          text: runs[r].digits.slice(at, at + len),
          sepBefore: k === 0 ? runs[r].sepBefore : '',
        })
        at += len
      })
    })
    if (groups.length < 3 || groups.length > 6) continue
    for (const order of DATE_ORDERS) {
      const tokens = [
        ...order.tokens,
        ...TIME_TOKENS.slice(0, groups.length - 3),
      ]
      if (!fits(groups, tokens)) continue
      const keep = kind === 'date' ? 3 : groups.length
      const fmt = groups
        .slice(0, keep)
        .map((g, i) => separatorRegex(g.sepBefore) + tokens[i])
        .join('')
      if (!found.includes(fmt)) found.push(fmt)
    }
  }
  return found
}

function fits(groups: Group[], tokens: string[]): boolean {
  return groups.every((g, i) => {
    const token = tokens[i]
    if (g.len !== (token === 'YYYY' ? 4 : 2)) return false
    const limit = LIMITS[token]
    if (!limit) return true
    const n = Number(g.text)
    return n >= limit[0] && n <= limit[1]
  })
}

/** The capture regex for a token format, for the plugin that takes the text
 * first and reads it with the format second (`civex.extract_from_filename`):
 * `YYYYMMDD[-_]HHmmSS` → `([0-9]{8}[-_][0-9]{6})`. */
export function captureForDateFormat(fmt: string): string {
  let body = ''
  let digits = 0
  for (const part of fmt.split(/(YYYY|MM|DD|HH|mm|SS)/)) {
    if (!part) continue
    if (/^(YYYY|MM|DD|HH|mm|SS)$/.test(part)) {
      digits += part.length
      continue
    }
    if (digits) body += `[0-9]{${digits}}`
    digits = 0
    body += part
  }
  if (digits) body += `[0-9]{${digits}}`
  return `(${body})`
}

const MONTHS = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
]

/** How a format reads `text`, for a person choosing between formats:
 * "11 June 2024 14:22:33 (year first)". */
export function describeDateFormat(text: string, fmt: string): string {
  const iso = parseFilenameByTokenFormat(text, fmt)
  const first = fmt.match(/YYYY|MM|DD/)?.[0]
  const note =
    first === 'YYYY'
      ? 'year first'
      : first === 'DD'
        ? 'day first'
        : 'month first'
  if (!iso) return fmt
  const [date, time] = iso.split('T')
  const [y, m, d] = date.split('-')
  const day = `${Number(d)} ${MONTHS[Number(m) - 1]} ${y}`
  return `${time ? `${day} ${time}` : day} (${note})`
}

/** Names that give the same key once it is compared as the records' field is
 * ("07" and "7" are one key; `civex.match_files_to_records`), by that key:
 * only keys more than one name gives. */
export function keyClashes(
  results: { filename: string; value: unknown }[],
): Map<string, string[]> {
  const byKey = new Map<string, string[]>()
  for (const r of results) {
    if (r.value === null || r.value === undefined || r.value === '') continue
    const key = normalizeNumericKey(String(r.value))
    byKey.set(key, [...(byKey.get(key) ?? []), r.filename])
  }
  for (const [key, names] of byKey) if (names.length < 2) byKey.delete(key)
  return byKey
}
