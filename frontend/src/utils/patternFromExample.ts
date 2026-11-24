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

const isDigit = (c: string) => c >= '0' && c <= '9'

/** `text` with every character that means something in a regex escaped, the
 * same way for JavaScript and Python. A dash is left alone: outside a set it
 * is a plain character in both. */
export function escapeRegex(text: string): string {
  return text.replace(/[\\^$.|?*+()[\]{}]/g, '\\$&')
}

/** What separates the parts of a name, and what a part is made of, as regex
 * sets (valid in JavaScript and Python). */
const SEP = '[ ._-]'
const PART = '[^ ._-]'

/** One part of a file name: a run between separators (` `, `.`, `_`, `-`). */
export interface NamePart {
  text: string
  start: number
  end: number
}

export function nameParts(name: string): NamePart[] {
  return [...name.matchAll(/[^ ._-]+/g)].map((m) => ({
    text: m[0],
    start: m.index,
    end: m.index + m[0].length,
  }))
}

/** The parts a person picked: `from` to `to` (inclusive), and for one part
 * with letters and digits, perhaps only the number in it (`dive07` -> 07). */
export interface PartChoice {
  from: number
  to: number
  digitsOnly: boolean
}

/** Whether "just the number in it" means something for this choice. */
export function hasNumberInside(parts: NamePart[], c: PartChoice): boolean {
  if (c.from !== c.to) return false
  const text = parts[c.from]?.text ?? ''
  return /[0-9]/.test(text) && /[^0-9]/.test(text)
}

function capture(c: PartChoice, parts: NamePart[]): string {
  if (c.digitsOnly) return '[^ ._0-9-]*([0-9]+)'
  const span = c.to - c.from
  // A number picked is taken as a number, so a letter after it isn't.
  if (!span && /^[0-9]+$/.test(parts[c.from]?.text ?? '')) return '([0-9]+)'
  return `(${PART}+${span ? `(?:${SEP}+${PART}+){${span}}` : ''})`
}

/** The choice found by its place: "the second part of the name", whatever
 * the parts say. */
export function placePattern(c: PartChoice, parts: NamePart[] = []): string {
  const skip = c.from === 0 ? '^' : `^(?:${PART}+${SEP}+){${c.from}}`
  return skip + capture(c, parts)
}

/** The text that comes just before the choice: the letters in front of the
 * number inside a part (`dive` of `dive07`), else the part before it and the
 * separator. Null when nothing comes before it. */
export function textBefore(
  name: string,
  parts: NamePart[],
  c: PartChoice,
): string | null {
  const part = parts[c.from]
  if (!part) return null
  if (c.digitsOnly) {
    const lead = part.text.slice(0, part.text.search(/[0-9]/))
    if (lead) return lead
  }
  const prev = parts[c.from - 1]
  if (!prev) return null
  return name.slice(prev.start, part.start)
}

/** The choice found by the text before it: names where it moves about but
 * always follows the same word. Null when nothing comes before it. */
export function textPattern(
  name: string,
  parts: NamePart[],
  c: PartChoice,
): string | null {
  const before = textBefore(name, parts, c)
  if (before === null) return null
  const part = parts[c.from]
  const inside = c.digitsOnly && part.text.startsWith(before)
  return escapeRegex(before) + (inside ? '([0-9]+)' : capture(c, parts))
}

const shape = (v: string) =>
  /^[0-9]+$/.test(v) ? 'digits' : /^[A-Za-z]+$/.test(v) ? 'letters' : 'mixed'

/** Whether a value taken from another name is the same sort of thing as the
 * one picked in the example: the same kind of characters and about as long
 * (`163` like `07`; not `20240612`). How two ways of finding a part are told
 * apart when both give every name a value. */
export function looksLike(value: string, picked: string): boolean {
  return (
    shape(value) === shape(picked) &&
    Math.abs(value.length - picked.length) <= Math.max(2, picked.length)
  )
}

const ORDINALS = ['first', 'second', 'third', 'fourth', 'fifth', 'sixth']
const nth = (i: number) => ORDINALS[i] ?? `${i + 1}th`

/** A pattern said in words, for the patterns this file writes ("the number
 * after “dive”", "the second part of the name"); null for anything else. */
export function describePattern(pattern: string): string | null {
  const SKIP = '^(?:[^ ._-]+[ ._-]+){'
  let from = 0
  let rest: string
  if (pattern.startsWith(SKIP)) {
    const m = /^\^\(\?:\[\^ \._-\]\+\[ \._-\]\+\)\{(\d+)\}/.exec(pattern)
    if (!m) return null
    from = Number(m[1])
    rest = pattern.slice(m[0].length)
  } else if (pattern.startsWith('^')) {
    rest = pattern.slice(1)
  } else {
    const at = pattern.search(
      /(\(\[0-9\]\+\)|\(\[\^ \._-\]\+\)|\[\^ \._0-9-\]\*\(\[0-9\]\+\))$/,
    )
    if (at <= 0) return null
    const before = pattern.slice(0, at).replace(/\\(.)/g, '$1')
    const taken = pattern.slice(at)
    const what = taken.includes('[0-9]+') ? 'the number' : 'the part'
    return `${what} after “${before}”`
  }
  if (rest === '[^ ._0-9-]*([0-9]+)')
    return `the number in the ${nth(from)} part of the name`
  if (rest === '([0-9]+)')
    return `the number that is the ${nth(from)} part of the name`
  const span =
    /^\(\[\^ \._-\]\+(?:\(\?:\[ \._-\]\+\[\^ \._-\]\+\)\{(\d+)\})?\)$/.exec(
      rest,
    )
  if (!span) return null
  const more = Number(span[1] ?? 0)
  return more
    ? `parts ${from + 1} to ${from + more + 1} of the name`
    : `the ${nth(from)} part of the name`
}

/** Where the choice is in the name, as offsets: for reading a date. */
export function choiceSpan(
  parts: NamePart[],
  c: PartChoice,
): { start: number; end: number } {
  return { start: parts[c.from].start, end: parts[c.to].end }
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
 * first and reads it with the format second (`civex.value_from_filename`):
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
 * ("07" and "7" are one key; `civex.save_records (files)`), by that key:
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
