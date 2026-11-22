import { afterEach, describe, it, expect } from 'vitest'
import {
  effectiveTimeZone,
  formatDateTime,
  formatFieldDate,
  formatInstantDate,
  formatTime,
  formatTimestamp,
  formatWallTime,
  isWallTime,
  knownTimeZone,
  parseWallTime,
  parseStoredInstant,
  utcToZonedLocal,
  zonedLocalToUTC,
} from './dates'
import { setDateFormat } from './dateFormat'

const CHI = 'America/Chicago'

describe('parseStoredInstant', () => {
  it('reads an offset-less value as UTC, not local time', () => {
    expect(parseStoredInstant('2024-03-01T15:30:00')?.toISOString()).toBe(
      '2024-03-01T15:30:00.000Z',
    )
    expect(parseStoredInstant('2024-03-01 15:30')?.toISOString()).toBe(
      '2024-03-01T15:30:00.000Z',
    )
  })
  it('honours explicit offsets', () => {
    expect(parseStoredInstant('2024-03-01T15:30:00+00:00')?.toISOString()).toBe(
      '2024-03-01T15:30:00.000Z',
    )
    expect(parseStoredInstant('2024-03-01T15:30:00-06:00')?.toISOString()).toBe(
      '2024-03-01T21:30:00.000Z',
    )
    expect(parseStoredInstant('2024-03-01T15:30:00Z')?.toISOString()).toBe(
      '2024-03-01T15:30:00.000Z',
    )
  })
  it('returns null for junk', () => {
    expect(parseStoredInstant('')).toBeNull()
    expect(parseStoredInstant('not a date')).toBeNull()
  })
})

describe('knownTimeZone / effectiveTimeZone', () => {
  it('drops unknown zones', () => {
    expect(knownTimeZone(CHI)).toBe(CHI)
    expect(knownTimeZone('Mars/Olympus')).toBeNull()
    expect(knownTimeZone('')).toBeNull()
    expect(knownTimeZone(null)).toBeNull()
  })
  it('field restriction beats collection, which beats unset', () => {
    const field = { restrictions: { timezone: 'Asia/Kolkata' } }
    expect(effectiveTimeZone(field, CHI)).toBe('Asia/Kolkata')
    expect(effectiveTimeZone({ restrictions: {} }, CHI)).toBe(CHI)
    expect(effectiveTimeZone({ restrictions: {} }, null)).toBeNull()
    expect(effectiveTimeZone(undefined, undefined)).toBeNull()
  })
})

describe('utcToZonedLocal', () => {
  it('shows the instant as wall time in the zone', () => {
    expect(utcToZonedLocal('2024-03-01T21:30:00+00:00', CHI)).toBe(
      '2024-03-01T15:30',
    ) // CST
    expect(utcToZonedLocal('2024-07-01T20:30:00+00:00', CHI)).toBe(
      '2024-07-01T15:30',
    ) // CDT
    expect(utcToZonedLocal('2024-03-01T06:30:00+00:00', 'Asia/Kolkata')).toBe(
      '2024-03-01T12:00',
    )
  })
  it('treats an offset-less stored value as UTC', () => {
    expect(utcToZonedLocal('2024-03-01T15:30:00', 'UTC')).toBe(
      '2024-03-01T15:30',
    )
    expect(utcToZonedLocal('2024-03-01T15:30:00', CHI)).toBe('2024-03-01T09:30')
  })
  it('keeps seconds, so they survive being shown and edited', () => {
    expect(utcToZonedLocal('2024-03-01T21:30:45+00:00', CHI)).toBe(
      '2024-03-01T15:30:45',
    )
    expect(utcToZonedLocal('2024-03-01T21:30:05Z', 'UTC')).toBe(
      '2024-03-01T21:30:05',
    )
  })
  it('round-trips seconds through the input and back to the stored instant', () => {
    const shown = utcToZonedLocal('2024-07-01T20:30:45.000Z', CHI)
    expect(shown).toBe('2024-07-01T15:30:45')
    expect(zonedLocalToUTC(shown, CHI)).toBe('2024-07-01T20:30:45.000Z')
  })
  it('handles the day rolling over', () => {
    expect(utcToZonedLocal('2024-03-01T02:00:00Z', CHI)).toBe(
      '2024-02-29T20:00',
    )
  })
  it('is empty for missing or bad input', () => {
    expect(utcToZonedLocal('', CHI)).toBe('')
    expect(utcToZonedLocal('junk', CHI)).toBe('')
  })
})

describe('zonedLocalToUTC', () => {
  it('reads wall time in the zone', () => {
    expect(zonedLocalToUTC('2024-03-01T15:30', CHI)).toBe(
      '2024-03-01T21:30:00.000Z',
    )
    expect(zonedLocalToUTC('2024-07-01T15:30', CHI)).toBe(
      '2024-07-01T20:30:00.000Z',
    )
    expect(zonedLocalToUTC('2024-03-01T12:00', 'Asia/Kolkata')).toBe(
      '2024-03-01T06:30:00.000Z',
    )
  })
  it('round-trips with utcToZonedLocal', () => {
    for (const iso of ['2024-01-15T03:00:00Z', '2024-06-15T23:59:00Z']) {
      const local = utcToZonedLocal(iso, CHI)
      expect(zonedLocalToUTC(local, CHI)).toBe(new Date(iso).toISOString())
    }
  })
  it('rejects a wall time the clocks skip (spring forward)', () => {
    expect(zonedLocalToUTC('2024-03-10T02:30', CHI)).toBeNull()
  })
  it('rejects a wall time the clocks repeat (fall back)', () => {
    expect(zonedLocalToUTC('2024-11-03T01:30', CHI)).toBeNull()
  })
  it('accepts times either side of a transition', () => {
    expect(zonedLocalToUTC('2024-03-10T01:59', CHI)).toBe(
      '2024-03-10T07:59:00.000Z',
    )
    expect(zonedLocalToUTC('2024-03-10T03:00', CHI)).toBe(
      '2024-03-10T08:00:00.000Z',
    )
    expect(zonedLocalToUTC('2024-11-03T00:59', CHI)).toBe(
      '2024-11-03T05:59:00.000Z',
    )
    expect(zonedLocalToUTC('2024-11-03T02:00', CHI)).toBe(
      '2024-11-03T08:00:00.000Z',
    )
  })
  it('agrees with the server on UTC, which has no transitions', () => {
    expect(zonedLocalToUTC('2024-11-03T01:30', 'UTC')).toBe(
      '2024-11-03T01:30:00.000Z',
    )
  })
  it('returns empty for empty input and null for junk', () => {
    expect(zonedLocalToUTC('', CHI)).toBe('')
    expect(zonedLocalToUTC('junk', CHI)).toBeNull()
  })
  it('with no zone reads in the viewer zone', () => {
    const local = '2024-03-01T15:30'
    expect(zonedLocalToUTC(local, null)).toBe(new Date(local).toISOString())
  })
  it('reads only wall time, never what Date would guess at', () => {
    // `new Date('01/03/2024 15:3')` is 3 January somewhere: half-typed text
    // must not become a date.
    expect(zonedLocalToUTC('01/03/2024 15:3', null)).toBeNull()
  })
})

describe('zonedLocalToUTC with seconds', () => {
  it('reads seconds as typed', () => {
    expect(zonedLocalToUTC('2024-07-01T15:30:42', CHI)).toBe(
      '2024-07-01T20:30:42.000Z',
    )
    expect(zonedLocalToUTC('2024-07-01T15:30:42', null)).not.toBeNull()
  })
  it('accepts a fraction of a second, as an input with a sub-minute step can report', () => {
    expect(zonedLocalToUTC('2024-07-01T15:30:42.000', CHI)).toBe(
      '2024-07-01T20:30:42.000Z',
    )
    expect(zonedLocalToUTC('2024-07-01T15:30:42.5', CHI)).toBe(
      '2024-07-01T20:30:42.500Z',
    )
  })
  it('still refuses a wall time that does not exist', () => {
    expect(zonedLocalToUTC('2024-03-10T02:30:15', CHI)).toBeNull() // DST gap
  })
})

describe('formatDateTime', () => {
  afterEach(() => localStorage.clear())

  it('shows the date in the chosen pattern, 24-hour wall time and the zone', () => {
    expect(formatDateTime('2024-03-01T21:30:00+00:00', CHI, 'en-US')).toBe(
      '01/03/2024 15:30 CST',
    )
    expect(formatDateTime('2024-07-01T20:30:00+00:00', CHI, 'en-US')).toBe(
      '01/07/2024 15:30 CDT',
    )
  })
  it('shows seconds when the value has them, and only then', () => {
    expect(formatDateTime('2024-03-01T21:30:45+00:00', CHI, 'en-US')).toBe(
      '01/03/2024 15:30:45 CST',
    )
    expect(formatDateTime('2024-03-01T21:30:00+00:00', CHI, 'en-US')).toBe(
      '01/03/2024 15:30 CST',
    )
  })
  it('follows each pattern', () => {
    const at = '2024-06-14T09:05:00+00:00'
    expect(formatDateTime(at, 'UTC', 'en-US', 'DD/MM/YYYY')).toBe(
      '14/06/2024 09:05 UTC',
    )
    expect(formatDateTime(at, 'UTC', 'en-US', 'MM/DD/YYYY')).toBe(
      '06/14/2024 09:05 UTC',
    )
    expect(formatDateTime(at, 'UTC', 'en-US', 'YYYY-MM-DD')).toBe(
      '2024-06-14 09:05 UTC',
    )
    expect(formatDateTime(at, 'UTC', 'en-US', 'D MMM YYYY')).toBe(
      '14 Jun 2024 09:05 UTC',
    )
  })
  it('follows the pattern chosen in settings', () => {
    setDateFormat('D MMM YYYY')
    expect(formatDateTime('2024-03-01T21:30:00Z', CHI, 'en-US')).toBe(
      '1 Mar 2024 15:30 CST',
    )
  })
  it('uses the wall date in the zone, not the UTC one', () => {
    // 03:30 UTC on 2 March is still 1 March in Chicago.
    expect(formatDateTime('2024-03-02T03:30:00Z', CHI, 'en-US')).toBe(
      '01/03/2024 21:30 CST',
    )
  })
  it('falls back to the raw value when unparseable', () => {
    expect(formatDateTime('junk', CHI, 'en-US')).toBe('junk')
  })
})

describe('formatTimestamp and friends', () => {
  afterEach(() => localStorage.clear())

  it('writes an instant in the viewer zone with no zone name', () => {
    const local = new Date(2024, 5, 14, 9, 5, 30)
    expect(formatTimestamp(local)).toBe('14/06/2024 09:05:30')
    expect(formatTimestamp(local, { seconds: false })).toBe('14/06/2024 09:05')
    expect(formatTimestamp(local.getTime())).toBe('14/06/2024 09:05:30')
    expect(formatTimestamp(local.toISOString())).toBe('14/06/2024 09:05:30')
    setDateFormat('MM/DD/YYYY')
    expect(formatTimestamp(local)).toBe('06/14/2024 09:05:30')
  })
  it('gives nothing for nothing, and junk as it is', () => {
    expect(formatTimestamp(null)).toBe('')
    expect(formatTimestamp('')).toBe('')
    expect(formatTimestamp('junk')).toBe('junk')
  })
  it('writes only the date, or only the time', () => {
    const local = new Date(2024, 5, 14, 9, 5)
    expect(formatInstantDate(local)).toBe('14/06/2024')
    expect(formatInstantDate('2024-03-02T03:30:00Z', CHI)).toBe('01/03/2024')
    expect(formatTime(local)).toBe('09:05')
  })
  it('writes a stored date or datetime value by its field type', () => {
    expect(formatFieldDate('2019-06', 'date')).toBe('06/2019')
    expect(formatFieldDate('2024-03-01T21:30:00Z', 'datetime', 'UTC')).toMatch(
      /^01\/03\/2024 21:30/,
    )
    expect(formatFieldDate('2019-06', 'string')).toBeNull()
    expect(formatFieldDate(2019, 'date')).toBeNull()
  })
})

describe('wall time as text', () => {
  afterEach(() => localStorage.clear())

  it('writes wall time in the chosen pattern', () => {
    expect(formatWallTime('2024-03-01T15:30')).toBe('01/03/2024 15:30')
    expect(formatWallTime('2024-03-01T15:30:45')).toBe('01/03/2024 15:30:45')
    expect(formatWallTime('2024-03-01T15:30', 'YYYY-MM-DD')).toBe(
      '2024-03-01 15:30',
    )
    expect(formatWallTime('junk')).toBe('')
  })
  it('reads typed text in each pattern', () => {
    expect(parseWallTime('01/03/2024 15:30')).toBe('2024-03-01T15:30')
    expect(parseWallTime('1/3/2024 9:05:07')).toBe('2024-03-01T09:05:07')
    expect(parseWallTime('03/01/2024 15:30', 'MM/DD/YYYY')).toBe(
      '2024-03-01T15:30',
    )
    expect(parseWallTime('2024-03-01 15:30', 'YYYY-MM-DD')).toBe(
      '2024-03-01T15:30',
    )
    expect(parseWallTime('1 Mar 2024 15:30', 'D MMM YYYY')).toBe(
      '2024-03-01T15:30',
    )
    // What a datetime input gives reads in every pattern.
    expect(parseWallTime('2024-03-01T15:30')).toBe('2024-03-01T15:30')
  })
  it('refuses a missing time, a bad time or a date short of a day', () => {
    expect(parseWallTime('01/03/2024')).toBeNull()
    expect(parseWallTime('01/03/2024 24:00')).toBeNull()
    expect(parseWallTime('01/03/2024 15:60')).toBeNull()
    expect(parseWallTime('03/2024 15:30')).toBeNull()
    expect(parseWallTime('31/02/2024 15:30')).toBeNull()
  })
  it('tells wall time from anything else', () => {
    expect(isWallTime('2024-03-01T15:30')).toBe(true)
    expect(isWallTime('2024-03-01T15:30:45.5')).toBe(true)
    expect(isWallTime('01/03/2024 15:30')).toBe(false)
  })
})
