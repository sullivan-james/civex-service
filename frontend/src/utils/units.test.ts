import { describe, expect, it } from 'vitest'
import {
  UNIT_GROUPS,
  canonicalUnit,
  convert,
  dimensionOf,
  parseQuantity,
  tidy,
  toFieldUnit,
} from './units'

describe('units', () => {
  it('converts between units of one dimension', () => {
    expect(convert(1024, 'ft', 'm')).toEqual({
      value: expect.closeTo(312.1152, 4),
    })
    expect(convert(0, '°C', 'K')).toEqual({ value: expect.closeTo(273.15, 6) })
    expect(convert(100, '°C', '°F')).toEqual({ value: expect.closeTo(212, 6) })
    expect(convert(5, 'm', 'm')).toEqual({ value: 5 })
  })

  it('refuses across dimensions and for unknown units', () => {
    expect(convert(1, 'm', 's')).toHaveProperty('error')
    expect(convert(1, 'umol/kg', 'm')).toHaveProperty('error')
  })

  it('resolves aliases and dimensions', () => {
    expect(canonicalUnit('degC')).toBe('°C')
    expect(dimensionOf('ft')).toBe('length')
    expect(dimensionOf('umol/kg')).toBeNull()
    expect(UNIT_GROUPS.length).toContain('fathom')
  })

  it('parses quantities', () => {
    expect(parseQuantity('1024')).toEqual({ value: 1024, unit: null })
    expect(parseQuantity('1024 ft')).toEqual({ value: 1024, unit: 'ft' })
    expect(parseQuantity('-3.5e2 m')).toEqual({ value: -350, unit: 'm' })
    expect(parseQuantity('deep')).toBeNull()
  })

  it('reads text in the field unit', () => {
    expect(toFieldUnit('312.4', 'm')).toEqual({ value: 312.4 })
    expect(toFieldUnit('1024 ft', 'm')).toEqual({
      value: expect.closeTo(312.1152, 4),
    })
    expect(toFieldUnit('5 m', null)).toHaveProperty('error')
    expect(toFieldUnit('abc', 'm')).toHaveProperty('error')
  })

  it('tidies binary noise', () => {
    expect(tidy(0.1 + 0.2)).toBe('0.3')
  })
})
