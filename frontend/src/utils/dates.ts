/**
 * Datetimes are stored as UTC instants. A timezone matters only for showing
 * an instant as wall time and for reading wall time a person typed in. The
 * zone for a field is `effectiveTimeZone`: the field's own `timezone`
 * restriction, else its collection's, else null -- meaning "the viewer's own
 * zone", which is how datetimes behaved before zones existed.
 *
 * Server counterpart: civex/domain/timezones.py (same DST rules).
 */

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
 * (null = the viewer's zone). Empty string if missing/unparseable. */
export function utcToZonedLocal(iso: string, tz: string | null = null): string {
  const d = parseStoredInstant(iso)
  if (!d) return ''
  const w = wallParts(d.getTime(), knownTimeZone(tz))
  return `${pad(w.year, 4)}-${pad(w.month)}-${pad(w.day)}T${pad(w.hour)}:${pad(w.minute)}`
}

const LOCAL_RE = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/

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
  if (!zone) {
    const d = new Date(local)
    return isNaN(d.getTime()) ? null : d.toISOString()
  }
  const m = LOCAL_RE.exec(local)
  if (!m) return null
  const [y, mo, d, h, mi, s] = m.slice(1).map((v) => (v ? Number(v) : 0))
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
  return new Date([...candidates][0]).toISOString()
}

/** The value to send for a typed datetime. Wall time the client can resolve
 * goes as an explicit UTC instant. One it can't -- a DST gap or overlap in
 * `tz` -- goes through unchanged, so the server (which applies the same
 * rules) rejects it with its own explanation instead of the client guessing. */
export function datetimeInputToWire(local: string, tz: string | null): string {
  return zonedLocalToUTC(local, tz) ?? local
}

/** Human-readable instant in `tz` with its zone abbreviation, e.g.
 * "Mar 1, 2024, 3:30 PM CST". Falls back to the raw value if unparseable. */
export function formatDateTime(
  iso: string,
  tz: string | null = null,
  locale?: string,
): string {
  const d = parseStoredInstant(iso)
  if (!d) return iso
  return new Intl.DateTimeFormat(locale, {
    timeZone: knownTimeZone(tz) ?? undefined,
    // dateStyle/timeStyle can't be combined with timeZoneName, so spell out the parts.
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
  }).format(d)
}

/** Stored UTC datetime -> <input type="datetime-local"> value in the viewer's zone. */
export function utcToDatetimeLocal(iso: string): string {
  return utcToZonedLocal(iso, null)
}

/** <input type="datetime-local"> value (viewer's zone) -> UTC ISO string. */
export function datetimeLocalToUTC(local: string): string {
  return zonedLocalToUTC(local, null) ?? ''
}
