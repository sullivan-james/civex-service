import { describe, it, expect } from 'vitest'
import { summarise, toInputProps, formatBytes } from './restrictions'
import { utcToDatetimeLocal } from './dates'
import type { Field } from '../api/schemas'

function makeField(overrides: Partial<Field>): Field {
  return {
    id: 'f1',
    name: 'field',
    label: null,
    type: 'string',
    required: false,
    restrictions: {},
    default: null,
    position: 0,
    ...overrides,
  }
}

describe('summarise', () => {
  it('formats integer/float restrictions', () => {
    expect(summarise({ min: 0, max: 10 }, 'integer')).toBe('min 0 · max 10')
  })

  it('formats string restrictions', () => {
    expect(summarise({ choices: ['a', 'b'], max_length: 5 }, 'string')).toBe(
      'choices: a, b · max 5 chars',
    )
  })

  it('formats file size restrictions using formatBytes', () => {
    expect(summarise({ max_size: 500 }, 'file')).toBe(`max ${formatBytes(500)}`)
    expect(summarise({ max_size: 2048 }, 'file')).toBe(
      `max ${formatBytes(2048)}`,
    )
  })

  it('formats date restrictions', () => {
    expect(summarise({ min: '2020-01-01', max: '2020-12-31' }, 'date')).toBe(
      'from 2020-01-01 · until 2020-12-31',
    )
  })

  it('returns empty string for no restrictions', () => {
    expect(summarise(undefined, 'string')).toBe('')
    expect(summarise({}, 'string')).toBe('')
  })
})

describe('formatBytes', () => {
  it('formats bytes, KB, and MB', () => {
    expect(formatBytes(500)).toBe('500 B')
    expect(formatBytes(2048)).toBe('2 KB')
    expect(formatBytes(5_242_880)).toBe('5.0 MB')
  })
})

describe('toInputProps', () => {
  it('exposes choices and maxLength for string fields', () => {
    const field = makeField({
      type: 'string',
      restrictions: { choices: ['a', 'b'], max_length: 10 },
    })
    expect(toInputProps(field)).toEqual({
      choices: ['a', 'b'],
      maxLength: 10,
    })
  })

  it('exposes min/max as numbers for integer/float fields', () => {
    const field = makeField({
      type: 'integer',
      restrictions: { min: 1, max: 5 },
    })
    expect(toInputProps(field)).toEqual({ min: 1, max: 5 })
  })

  it('exposes accept/maxSize for file fields', () => {
    const field = makeField({
      type: 'file',
      restrictions: { accept: '.png', max_size: 1024 },
    })
    expect(toInputProps(field)).toEqual({ accept: '.png', maxSize: 1024 })
  })

  it('exposes targetSchema for reference fields', () => {
    const field = makeField({
      type: 'reference',
      restrictions: { schema: 'Patient' },
    })
    expect(toInputProps(field)).toEqual({ targetSchema: 'Patient' })
  })

  it('converts datetime min/max to local for the datetime-local input', () => {
    const field = makeField({
      type: 'datetime',
      restrictions: { min: '2020-06-15T10:30:00.000Z' },
    })
    expect(toInputProps(field)).toEqual({
      minDate: utcToDatetimeLocal('2020-06-15T10:30:00.000Z'),
    })
  })

  it('returns an empty object for fields without restriction keys', () => {
    expect(
      toInputProps(makeField({ type: 'boolean', restrictions: {} })),
    ).toEqual({})
  })
})

describe('datetime timezone restriction', () => {
  const CHI = 'America/Chicago'

  it('expresses input bounds in the effective zone', () => {
    const field = makeField({
      type: 'datetime',
      restrictions: { min: '2024-03-01T21:30:00Z' },
    })
    expect(toInputProps(field, CHI).minDate).toBe('2024-03-01T15:30')
    expect(toInputProps(field, 'UTC').minDate).toBe('2024-03-01T21:30')
  })

  it('shows the zone in the summary', () => {
    expect(summarise({ timezone: CHI }, 'datetime')).toBe(`timezone ${CHI}`)
  })
})
