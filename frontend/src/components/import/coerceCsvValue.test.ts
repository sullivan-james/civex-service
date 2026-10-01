import { describe, expect, it } from 'vitest'
import { coerceCsvValue } from './importWizardTypes'

describe('coerceCsvValue with units and locations', () => {
  it('converts a column written in another unit into the field unit', () => {
    const r = coerceCsvValue('1024', 'float', {
      fieldUnit: 'm',
      columnUnit: 'ft',
    })
    expect(r.error).toBeNull()
    expect(r.value).toBeCloseTo(312.1152, 3)
  })

  it('takes a bare number as already in the field unit', () => {
    expect(coerceCsvValue('312.4', 'float', { fieldUnit: 'm' })).toEqual({
      value: 312.4,
      error: null,
    })
  })

  it('lets a unit typed in the cell win over the column unit', () => {
    const r = coerceCsvValue('1 km', 'float', {
      fieldUnit: 'm',
      columnUnit: 'ft',
    })
    expect(r.value).toBe(1000)
  })

  it('refuses units that do not convert', () => {
    expect(coerceCsvValue('5 s', 'float', { fieldUnit: 'm' }).error).toMatch(
      /Can't convert/,
    )
  })

  it('leaves unitless floats as before', () => {
    expect(coerceCsvValue('2.5', 'float')).toEqual({ value: 2.5, error: null })
  })

  it('reads a location', () => {
    expect(coerceCsvValue('56.12, -3.41', 'geo').value).toEqual({
      type: 'Point',
      coordinates: [-3.41, 56.12],
    })
    expect(coerceCsvValue('harbour', 'geo').error).toMatch(/not a location/)
  })
})
