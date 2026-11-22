/**
 * How dates are written on screen: the one pattern a person picks in
 * Settings → Appearance → Date format, per browser (like the theme), and the
 * functions that write and read calendar dates in it.
 *
 * Display only: what is stored, sent to the server and written into exports
 * stays ISO (`2019-06-14`). Instants (datetimes) are written by
 * `utils/dates` (`formatDateTime`, `formatTimestamp`, `formatInstantDate`),
 * which use the pattern from here for their date part.
 *
 * Calendar dates may be partial (`utils/partialDates`): a year (`2019`), a
 * month (`2019-06`) or a day (`2019-06-14`), and are written at the
 * precision they have.
 */
import { isValidPartialDate, precisionOf, type Precision } from './partialDates'

export const DATE_FORMATS = [
  'DD/MM/YYYY',
  'MM/DD/YYYY',
  'YYYY-MM-DD',
  'D MMM YYYY',
] as const
export type DateFormat = (typeof DATE_FORMATS)[number]
export const DEFAULT_DATE_FORMAT: DateFormat = 'DD/MM/YYYY'

const STORAGE_KEY = 'civex-date-format'
const CHANGE_EVENT = 'civex-date-format'

function isDateFormat(value: unknown): value is DateFormat {
  return (DATE_FORMATS as readonly unknown[]).includes(value)
}

/** The chosen pattern (the default when none is chosen or storage is
 * blocked). */
export function getDateFormat(): DateFormat {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    return isDateFormat(stored) ? stored : DEFAULT_DATE_FORMAT
  } catch {
    return DEFAULT_DATE_FORMAT
  }
}

/** Choose a pattern; every date on screen follows at once
 * (`hooks/useDateFormat` re-renders the app). */
export function setDateFormat(format: DateFormat) {
  try {
    if (format === DEFAULT_DATE_FORMAT) localStorage.removeItem(STORAGE_KEY)
    else localStorage.setItem(STORAGE_KEY, format)
  } catch {
    // Storage blocked: the choice lasts this page only.
  }
  window.dispatchEvent(new Event(CHANGE_EVENT))
}

export function subscribeDateFormat(onChange: () => void) {
  window.addEventListener(CHANGE_EVENT, onChange)
  window.addEventListener('storage', onChange)
  return () => {
    window.removeEventListener(CHANGE_EVENT, onChange)
    window.removeEventListener('storage', onChange)
  }
}

const MONTHS = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
]
const pad = (n: number, width = 2) => String(n).padStart(width, '0')

/** A year, a month or a day (`month`/`day` 1-based) in `format`. */
export function formatDateParts(
  year: number,
  month?: number,
  day?: number,
  format: DateFormat = getDateFormat(),
): string {
  const y = pad(year, 4)
  if (month === undefined) return y
  const m = pad(month)
  if (day === undefined) {
    if (format === 'YYYY-MM-DD') return `${y}-${m}`
    if (format === 'D MMM YYYY') return `${MONTHS[month - 1]} ${y}`
    return `${m}/${y}`
  }
  const d = pad(day)
  switch (format) {
    case 'DD/MM/YYYY':
      return `${d}/${m}/${y}`
    case 'MM/DD/YYYY':
      return `${m}/${d}/${y}`
    case 'YYYY-MM-DD':
      return `${y}-${m}-${d}`
    case 'D MMM YYYY':
      return `${day} ${MONTHS[month - 1]} ${y}`
  }
}

/** A calendar date as stored (`2019`, `2019-06`, `2019-06-14`) in the chosen
 * pattern, at the precision it has. Anything else is returned unchanged, so
 * an odd stored value is still shown as it is. */
export function formatDate(
  value: string,
  format: DateFormat = getDateFormat(),
): string {
  const text = value.trim()
  if (!isValidPartialDate(text)) return value
  const year = Number(text.slice(0, 4))
  const month = text.length >= 7 ? Number(text.slice(5, 7)) : undefined
  const day = text.length >= 10 ? Number(text.slice(8, 10)) : undefined
  return formatDateParts(year, month, day, format)
}

/** What to type, as a placeholder: the pattern at each precision allowed. */
export function datePlaceholder(
  least: Precision = 'day',
  format: DateFormat = getDateFormat(),
): string {
  const forms = {
    year: 'YYYY',
    month:
      format === 'YYYY-MM-DD'
        ? 'YYYY-MM'
        : format === 'D MMM YYYY'
          ? 'MMM YYYY'
          : 'MM/YYYY',
    day: format,
  }
  if (least === 'day') return forms.day
  if (least === 'month') return `${forms.month} or ${forms.day}`
  return `${forms.year}, ${forms.month} or ${forms.day}`
}

function monthNumber(word: string): number | null {
  const w = word.toLowerCase()
  if (w.length < 3) return null
  const i = MONTHS.findIndex((m) => w.startsWith(m.toLowerCase()))
  return i === -1 ? null : i + 1
}

/** Typed text -> the stored form (`2019`, `2019-06`, `2019-06-14`), or null
 * when it isn't a real date in `format`. Separators may be `/`, `-`, `.` or
 * spaces; day and month may have one digit; the year needs four. An ISO date
 * (`2019-06-14`, `2019-06`) is read in every pattern, since it can't be
 * mistaken for anything else. A bare four-digit number is a year. */
export function parseDate(
  text: string,
  format: DateFormat = getDateFormat(),
): string | null {
  const t = text.trim()
  if (!t) return null
  const iso = /^(\d{4})(?:[-/.](\d{1,2})(?:[-/.](\d{1,2}))?)?$/.exec(t)
  let year: string, month: string | undefined, day: string | undefined
  if (iso) {
    ;[, year, month, day] = iso
  } else if (format === 'D MMM YYYY') {
    const m = /^(?:(\d{1,2})[\s.-]+)?([A-Za-z]+)\.?[\s,.-]+(\d{4})$/.exec(t)
    if (!m) return null
    const n = monthNumber(m[2])
    if (n === null) return null
    ;[day, month, year] = [m[1], String(n), m[3]]
  } else {
    const parts = t.split(/\s*[-/.\s]\s*/)
    if (parts.some((p) => !/^\d+$/.test(p))) return null
    if (parts.length === 2) [month, year] = parts
    else if (parts.length === 3) {
      if (format === 'MM/DD/YYYY') [month, day, year] = parts
      else if (format === 'DD/MM/YYYY') [day, month, year] = parts
      else return null // YYYY-MM-DD: only the ISO order, handled above
    } else return null
  }
  if (!/^\d{4}$/.test(year)) return null
  if ((month && month.length > 2) || (day && day.length > 2)) return null
  const stored = [year, month && pad(Number(month)), day && pad(Number(day))]
    .filter(Boolean)
    .join('-')
  return isValidPartialDate(stored) ? stored : null
}

/** Like `parseDate`, and at least as precise as `least`. */
export function parseDateAtLeast(
  text: string,
  least: Precision,
  format: DateFormat = getDateFormat(),
): string | null {
  const stored = parseDate(text, format)
  if (stored === null) return null
  const order = ['year', 'month', 'day']
  return order.indexOf(precisionOf(stored)!) >= order.indexOf(least)
    ? stored
    : null
}
