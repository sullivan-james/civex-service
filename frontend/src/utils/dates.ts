/**
 * Datetimes are stored as UTC instants. A timezone matters only for showing
 * an instant as wall time and for reading wall time a person typed in. The
 * zone for a field is `effectiveTimeZone`: the field's own `timezone`
 * restriction, else its collection's, else null -- meaning "the viewer's own
 * zone", which is how datetimes behaved before zones existed.
 *
 * Server counterpart: civex/domain/timezones.py (same DST rules).
 *
 * Every date and time on screen is written here or in `./dateFormat` (the
 * pattern chosen in Settings → Appearance); nothing else formats dates.
 */
import {
  formatDate,
  formatDateParts,
  getDateFormat,
  parseDateAtLeast,
  type DateFormat,
} from './dateFormat'

export {
  DATE_FORMATS,
  DEFAULT_DATE_FORMAT,
  datePlaceholder,
  formatDate,
  parseDate,
  parseDateAtLeast,
  type DateFormat,
} from './dateFormat'

// "2024-03-01T15:30" / "2024-03-01 15:30:00" -- no Z, no +hh:mm.
const OFFSETLESS = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/

/** Parse a stored datetime. A value with no offset is UTC (civex's rule for
 * rows written before datetimes were normalised); `new Date()` would read
 * it as local time instead. Returns null if unparseable. */
export function parseStoredInstant(iso: string): Date | null {
  if (!iso) return null
  const s = iso.trim()
  const d = new Date(OFFSETLESS.test(s) ? `${s.replace(' ', 'T')}Z` : s)
  return isNaN(d.getTime()) ? null : d
}

/** `tz` if the runtime knows it, else null (treated as unset). */
export function knownTimeZone(tz: string | null | undefined): string | null {
  if (!tz) return null
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: tz })
    return tz
  } catch {
    return null
  }
}

/** A field's own `timezone` restriction wins over its collection's. */
export function effectiveTimeZone(
  field: { restrictions?: Record<string, unknown> } | undefined,
  collectionTimeZone: string | null | undefined,
): string | null {
  const own = field?.restrictions?.timezone
  return knownTimeZone(typeof own === 'string' ? own : collectionTimeZone)
}

interface WallParts {
  year: number
  month: number
  day: number
  hour: number
  minute: number
  second: number
}

function wallParts(ms: number, tz: string | null): WallParts {
  const fmt = new Intl.DateTimeFormat('en-US', {
    timeZone: tz ?? undefined,
    hourCycle: 'h23',
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    hour: 'numeric',
    minute: 'numeric',
    second: 'numeric',
  })
  const p: Record<string, number> = {}
  for (const part of fmt.formatToParts(new Date(ms))) {
    if (part.type !== 'literal') p[part.type] = Number(part.value)
  }
  return {
    year: p.year,
    month: p.month,
    day: p.day,
    hour: p.hour,
    minute: p.minute,
    second: p.second,
  }
}

const pad = (n: number, width = 2) => String(n).padStart(width, '0')

/** Stored UTC instant -> value for <input type="datetime-local"> in `tz`
 * (null = the viewer's zone). Empty string if missing/unparseable. Seconds are
 * included when the value has them (the input must have `step={1}` to show and
 * keep them), so a minute-aligned value reads exactly as it always did.
 * Fractions of a second are not shown. */
export function utcToZonedLocal(iso: string, tz: string | null = null): string {
  const d = parseStoredInstant(iso)
  if (!d) return ''
  const w = wallParts(d.getTime(), knownTimeZone(tz))
  const minute = `${pad(w.year, 4)}-${pad(w.month)}-${pad(w.day)}T${pad(w.hour)}:${pad(w.minute)}`
  return w.second ? `${minute}:${pad(w.second)}` : minute
}

// Seconds are optional, and so is a fraction of one (an input with a sub-minute
// step can report `:45.000`); the fraction is kept to the millisecond.
const LOCAL_RE =
  /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?$/

/** A <input type="datetime-local"> value read as wall time in `tz` -> UTC ISO
 * string. '' for empty input. Returns null when the wall time can't be
 * resolved to one instant: it doesn't exist (clocks skip it) or is ambiguous
 * (clocks repeat it) in that zone, or the text isn't a datetime. With no
 * zone it reads in the viewer's zone, as before. */
export function zonedLocalToUTC(
  local: string,
  tz: string | null = null,
): string | null {
  if (!local) return ''
  const zone = knownTimeZone(tz)
  // Only wall time as an input gives it: `new Date()` would read nearly any
  // text ("01/03/2024 15:3") as something.
  if (!LOCAL_RE.test(local)) return null
  if (!zone) {
    const d = new Date(local)
    return isNaN(d.getTime()) ? null : d.toISOString()
  }
  const m = LOCAL_RE.exec(local)!
  const [y, mo, d, h, mi, s] = m.slice(1, 7).map((v) => (v ? Number(v) : 0))
  const ms = m[7] ? Number(m[7].slice(0, 3).padEnd(3, '0')) : 0
  const asUtc = Date.UTC(y, mo - 1, d, h, mi, s)
  const offsetAt = (ms: number) => {
    const w = wallParts(ms, zone)
    return Date.UTC(w.year, w.month - 1, w.day, w.hour, w.minute, w.second) - ms
  }
  // Only the offsets in force a day either side of the wall time can apply
  // to it; a candidate instant is real if it reads back as the same wall time.
  const DAY = 86_400_000
  const candidates = new Set<number>()
  for (const o of new Set([offsetAt(asUtc - DAY), offsetAt(asUtc + DAY)])) {
    const t = asUtc - o
    if (offsetAt(t) === o) candidates.add(t)
  }
  if (candidates.size !== 1) return null
  return new Date([...candidates][0] + ms).toISOString()
}

/** The value to send for a typed datetime. Wall time the client can resolve
 * goes as an explicit UTC instant. One it can't -- a DST gap or overlap in
 * `tz` -- goes through unchanged, so the server (which applies the same
 * rules) rejects it with its own explanation instead of the client guessing. */
export function datetimeInputToWire(local: string, tz: string | null): string {
  return zonedLocalToUTC(local, tz) ?? local
}

/** True for wall time as a datetime input gives it: `2024-03-01T15:30`,
 * with optional seconds and fraction. */
export function isWallTime(local: string): boolean {
  return LOCAL_RE.test(local)
}

type InstantLike = string | number | Date

function toInstant(value: InstantLike): Date | null {
  if (value instanceof Date) return isNaN(value.getTime()) ? null : value
  if (typeof value === 'number') {
    const d = new Date(value)
    return isNaN(d.getTime()) ? null : d
  }
  return parseStoredInstant(value)
}

function timeOf(w: WallParts, seconds = true): string {
  const minute = `${pad(w.hour)}:${pad(w.minute)}`
  // Seconds only when there are some, so minute-aligned values stay compact.
  return seconds && w.second ? `${minute}:${pad(w.second)}` : minute
}

/** The zone's short name at that instant ("CST", "GMT+1"), in `locale`
 * (the browser's by default). */
function zoneLabel(d: Date, tz: string | null, locale?: string): string {
  const part = new Intl.DateTimeFormat(locale, {
    timeZone: tz ?? undefined,
    timeZoneName: 'short',
  })
    .formatToParts(d)
    .find((p) => p.type === 'timeZoneName')
  return part?.value ?? ''
}

/** A datetime field's value: the date in the chosen pattern
 * (`utils/dateFormat`), 24-hour time in `tz` (null = the viewer's zone) with
 * seconds when it has them, and the zone's short name, e.g.
 * "01/03/2024 15:30 CST". Falls back to the raw value if unparseable. */
export function formatDateTime(
  iso: string,
  tz: string | null = null,
  locale?: string,
  format: DateFormat = getDateFormat(),
): string {
  const d = parseStoredInstant(iso)
  if (!d) return iso
  const zone = knownTimeZone(tz)
  const w = wallParts(d.getTime(), zone)
  const label = zoneLabel(d, zone, locale)
  const text = `${formatDateParts(w.year, w.month, w.day, format)} ${timeOf(w)}`
  return label ? `${text} ${label}` : text
}

/** When something happened (a run, a change, a sync), in the viewer's zone:
 * the date in the chosen pattern and 24-hour time, seconds when it has them.
 * No zone name: these are always the viewer's own time. `seconds: false`
 * leaves them out (a compact list). '' for a missing value; an unreadable
 * string is returned as it is. */
export function formatTimestamp(
  value: InstantLike | null | undefined,
  { seconds = true }: { seconds?: boolean } = {},
): string {
  if (value === null || value === undefined || value === '') return ''
  const d = toInstant(value)
  if (!d) return typeof value === 'string' ? value : ''
  const w = wallParts(d.getTime(), null)
  return `${formatDateParts(w.year, w.month, w.day)} ${timeOf(w, seconds)}`
}

/** Only the date of an instant, in `tz` (null = the viewer's zone). */
export function formatInstantDate(
  value: InstantLike | null | undefined,
  tz: string | null = null,
  format: DateFormat = getDateFormat(),
): string {
  if (value === null || value === undefined || value === '') return ''
  const d = toInstant(value)
  if (!d) return typeof value === 'string' ? value : ''
  const w = wallParts(d.getTime(), knownTimeZone(tz))
  return formatDateParts(w.year, w.month, w.day, format)
}

/** Only the 24-hour time of an instant, in the viewer's zone. */
export function formatTime(
  value: InstantLike | null | undefined,
  { seconds = true }: { seconds?: boolean } = {},
): string {
  if (value === null || value === undefined || value === '') return ''
  const d = toInstant(value)
  if (!d) return ''
  return timeOf(wallParts(d.getTime(), null), seconds)
}

/** Wall time (`2024-03-01T15:30[:45]`, as `utcToZonedLocal` gives it) as
 * text in the chosen pattern: "01/03/2024 15:30". '' for anything else. */
export function formatWallTime(
  local: string,
  format: DateFormat = getDateFormat(),
): string {
  const m = LOCAL_RE.exec(local)
  if (!m) return ''
  const [y, mo, d, h, mi, s] = m.slice(1, 7).map((v) => (v ? Number(v) : 0))
  return `${formatDateParts(y, mo, d, format)} ${timeOf({
    year: y,
    month: mo,
    day: d,
    hour: h,
    minute: mi,
    second: s,
  })}`
}

/** Typed date and time -> wall time (`2024-03-01T15:30[:45]`), or null.
 * The date is read in the chosen pattern (`parseDate`, a full day needed),
 * the time is 24-hour `H:MM` or `H:MM:SS` after a space, `T` or comma. */
export function parseWallTime(
  text: string,
  format: DateFormat = getDateFormat(),
): string | null {
  const m = /^(.*?)[\s,T]+(\d{1,2}):(\d{2})(?::(\d{2}))?$/.exec(text.trim())
  if (!m) return null
  const day = parseDateAtLeast(m[1], 'day', format)
  if (!day) return null
  const [h, mi, s] = [m[2], m[3], m[4]].map((v) => (v ? Number(v) : 0))
  if (h > 23 || mi > 59 || s > 59) return null
  const time = `${pad(h)}:${pad(mi)}`
  return `${day}T${m[4] ? `${time}:${pad(s)}` : time}`
}

/** Stored UTC datetime -> <input type="datetime-local"> value in the viewer's zone. */
export function utcToDatetimeLocal(iso: string): string {
  return utcToZonedLocal(iso, null)
}

/** <input type="datetime-local"> value (viewer's zone) -> UTC ISO string. */
export function datetimeLocalToUTC(local: string): string {
  return zonedLocalToUTC(local, null) ?? ''
}

/** A `date` or `datetime` field's stored value as shown (a datetime in `tz`,
 * null = the viewer's zone), or null for any other type or value, so a
 * generic value renderer can ask first and fall back to its own text. */
export function formatFieldDate(
  value: unknown,
  dtype: string | null | undefined,
  tz: string | null = null,
): string | null {
  if (typeof value !== 'string' || !value) return null
  if (dtype === 'date') return formatDate(value)
  if (dtype === 'datetime') return formatDateTime(value, tz)
  return null
}
