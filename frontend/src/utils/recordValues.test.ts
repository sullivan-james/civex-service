import { describe, it, expect } from 'vitest'
import {
  buildRecordData,
  coerceFieldValue,
  isEmptyValue,
  sameValue,
  withFieldValue,
} from './recordValues'

describe('coerceFieldValue', () => {
  it('parses numeric strings by field type', () => {
    expect(coerceFieldValue('7', 'integer')).toBe(7)
    expect(coerceFieldValue('2.5', 'float')).toBe(2.5)
  })
  it('turns empty values into undefined but keeps false and 0', () => {
    expect(coerceFieldValue('', 'string')).toBeUndefined()
    expect(coerceFieldValue(null, 'string')).toBeUndefined()
    expect(coerceFieldValue([], 'tags')).toBeUndefined()
    expect(coerceFieldValue(false, 'boolean')).toBe(false)
    expect(coerceFieldValue('0', 'integer')).toBe(0)
  })
})

describe('buildRecordData', () => {
  it('omits unset fields', () => {
    const fields = [
      { name: 'a', type: 'integer' },
      { name: 'b', type: 'string' },
    ]
    expect(buildRecordData(fields, { a: '3', b: '' })).toEqual({ a: 3 })
  })
})

describe('withFieldValue', () => {
  it('keeps every other field, since PATCH replaces record data', () => {
    const data = { a: 1, b: 'x' }
    expect(withFieldValue(data, 'a', 2)).toEqual({ a: 2, b: 'x' })
    expect(data).toEqual({ a: 1, b: 'x' })
  })
  it('removes the key when cleared', () => {
    expect(withFieldValue({ a: 1, b: 'x' }, 'b', undefined)).toEqual({ a: 1 })
  })
})

describe('sameValue / isEmptyValue', () => {
  it('treats all empties as equal', () => {
    expect(sameValue(undefined, '')).toBe(true)
    expect(sameValue(null, [])).toBe(true)
    expect(isEmptyValue(0)).toBe(false)
  })
  it('compares structures', () => {
    expect(sameValue({ sha256: 'a' }, { sha256: 'a' })).toBe(true)
    expect(sameValue(['a'], ['b'])).toBe(false)
  })
})
