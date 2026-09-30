import { describe, it, expect } from 'vitest'
import {
  effectiveTimeZone,
  formatDateTime,
  knownTimeZone,
  parseStoredInstant,
  utcToZonedLocal,
  zonedLocalToUTC,
} from './dates'

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
})

describe('formatDateTime', () => {
  it('shows wall time with the zone abbreviation', () => {
    expect(formatDateTime('2024-03-01T21:30:00+00:00', CHI, 'en-US')).toBe(
      'Mar 1, 2024, 3:30 PM CST',
    )
    expect(formatDateTime('2024-07-01T20:30:00+00:00', CHI, 'en-US')).toBe(
      'Jul 1, 2024, 3:30 PM CDT',
    )
  })
  it('falls back to the raw value when unparseable', () => {
    expect(formatDateTime('junk', CHI, 'en-US')).toBe('junk')
  })
})
