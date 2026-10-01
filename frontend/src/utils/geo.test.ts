import { describe, expect, it } from 'vitest'
import { editableText, formatLocation, isGeometry, parseLocation } from './geo'

describe('geo', () => {
  it('reads latitude, longitude as a point (longitude first in GeoJSON)', () => {
    expect(parseLocation('56.12, -3.41')).toEqual({
      type: 'Point',
      coordinates: [-3.41, 56.12],
    })
    expect(parseLocation('56.12 -3.41')?.coordinates).toEqual([-3.41, 56.12])
  })

  it('reads WKT and GeoJSON', () => {
    expect(parseLocation('POINT(-3.41 56.12)')?.coordinates).toEqual([
      -3.41, 56.12,
    ])
    expect(
      parseLocation('{"type":"Point","coordinates":[1,2]}')?.coordinates,
    ).toEqual([1, 2])
  })

  it('rejects nonsense and out-of-range points', () => {
    expect(parseLocation('near the harbour')).toBeNull()
    expect(parseLocation('91, 0')).toBeNull()
    expect(parseLocation('0, 181')).toBeNull()
    expect(parseLocation('{"type":"Circle","coordinates":[0,0]}')).toBeNull()
  })

  it('formats for display and editing', () => {
    const p = { type: 'Point', coordinates: [-3.41, 56.12] }
    expect(formatLocation(p)).toBe('56.12, -3.41')
    expect(editableText(p)).toBe('56.12, -3.41')
    expect(formatLocation({ type: 'Polygon', coordinates: [] })).toBe('Polygon')
    expect(
      editableText({ type: 'Point', coordinates: [1, 2, -300] }),
    ).toContain('{')
    expect(isGeometry(p)).toBe(true)
    expect(isGeometry({ sha256: 'x' })).toBe(false)
  })
})
