import { describe, expect, it } from 'vitest'
import {
  fromDms,
  formatCoordinate,
  normalizeLon,
  parseCoordinates,
  toDms,
} from './geoCoords'
import {
  formatArea,
  formatLength,
  lineLengthMeters,
  ringAreaSqMeters,
} from './geoMeasure'

// The same table is asserted by tests/domain/test_geo.py: the CLI/CSV reader
// and the browser must agree on what a typed location means.
const VECTORS: [string, [number, number]][] = [
  ['56.12, -3.41', [56.12, -3.41]],
  ['56.12 -3.41', [56.12, -3.41]],
  ['56.12N 3.41W', [56.12, -3.41]],
  ['56.12 N, 3.41 W', [56.12, -3.41]],
  ['N56.12 W3.41', [56.12, -3.41]],
  ['3.41W 56.12N', [56.12, -3.41]],
  ['56°07\'12"N 3°24\'36"W', [56.12, -3.41]],
  ["N 56° 07.2' W 3° 24.6'", [56.12, -3.41]],
  ['56°07\'12" -3°24\'36"', [56.12, -3.41]],
  ['56 07 12 N, 3 24 36 W', [56.12, -3.41]],
  ['33.5S 151.2E', [-33.5, 151.2]],
]
const REJECTS = ['nonsense', '56N 3N', "56°75'N 3°W", '-56N 3W', '56', '1 2 3']

describe('parseCoordinates', () => {
  it.each(VECTORS)('reads %s', (text, [lat, lon]) => {
    const got = parseCoordinates(text)
    expect(got?.[0]).toBeCloseTo(lat, 9)
    expect(got?.[1]).toBeCloseTo(lon, 9)
  })
  it.each(REJECTS)('rejects %s', (text) => {
    expect(parseCoordinates(text)).toBeNull()
  })
})

describe('formatting', () => {
  it('writes each format', () => {
    expect(formatCoordinate(56.12, 'lat', 'dd')).toBe('56.12° N')
    expect(formatCoordinate(-3.41, 'lon', 'dd')).toBe('3.41° W')
    expect(formatCoordinate(56.12, 'lat', 'ddm')).toBe('56° 7.2′ N')
    expect(formatCoordinate(-3.41, 'lon', 'dms')).toBe('3° 24′ 36″ W')
  })

  it('what it writes it can read back', () => {
    for (const fmt of ['dd', 'ddm', 'dms'] as const) {
      const text = `${formatCoordinate(56.12, 'lat', fmt)} ${formatCoordinate(-3.41, 'lon', fmt)}`
      const got = parseCoordinates(text)
      expect(got?.[0]).toBeCloseTo(56.12, 5)
      expect(got?.[1]).toBeCloseTo(-3.41, 5)
    }
  })

  it('carries rounding instead of printing 60', () => {
    const d = toDms(10.99999999)
    expect(d.seconds).toBeLessThan(60)
    expect(fromDms(toDms(-3.41))).toBeCloseTo(-3.41, 9)
  })

  it('wraps longitudes', () => {
    expect(normalizeLon(190)).toBe(-170)
    expect(normalizeLon(-190)).toBe(170)
    expect(normalizeLon(179.5)).toBe(179.5)
  })
})

describe('measurements', () => {
  it('measures a line', () => {
    // one degree of latitude is about 111.2 km
    expect(
      lineLengthMeters([
        [0, 0],
        [0, 1],
      ]),
    ).toBeCloseTo(111195, -2)
  })

  it('measures an area', () => {
    // 1° x 1° at the equator is about 12,364 km²
    const ring = [
      [0, 0],
      [1, 0],
      [1, 1],
      [0, 1],
      [0, 0],
    ]
    expect(ringAreaSqMeters(ring) / 1e6).toBeCloseTo(12364, -2)
  })

  it('formats sizes', () => {
    expect(formatLength(8.4)).toBe('8.4 m')
    expect(formatLength(38200)).toBe('38.2 km')
    expect(formatArea(250)).toBe('250 m²')
    expect(formatArea(2_500_000)).toBe('2.50 km²')
  })
})
