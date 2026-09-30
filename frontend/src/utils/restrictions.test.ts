import { describe, it, expect } from 'vitest'
import {
  build,
  parse,
  summarise,
  toInputProps,
  boundsProblem,
  formatBytes,
  EMPTY_RESTRICTION_STATE,
} from './restrictions'
import { utcToDatetimeLocal, datetimeLocalToUTC } from './dates'
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

describe('build/parse round-trip', () => {
  it('integer: min/max', () => {
    const restrictions = build('integer', {
      ...EMPTY_RESTRICTION_STATE,
      min: '0',
      max: '10',
    })
    expect(restrictions).toEqual({ min: 0, max: 10 })
    const field = makeField({ type: 'integer', restrictions })
    expect(parse(field)).toMatchObject({ min: '0', max: '10' })
  })

  it('float: min/max', () => {
    const restrictions = build('float', {
      ...EMPTY_RESTRICTION_STATE,
      min: '0.5',
      max: '9.5',
    })
    expect(restrictions).toEqual({ min: 0.5, max: 9.5 })
    const field = makeField({ type: 'float', restrictions })
    expect(parse(field)).toMatchObject({ min: '0.5', max: '9.5' })
  })

  it('string: choices and max_length', () => {
    const restrictions = build('string', {
      ...EMPTY_RESTRICTION_STATE,
      choices: 'left, right, bilateral',
      maxLength: '20',
    })
    expect(restrictions).toEqual({
      choices: ['left', 'right', 'bilateral'],
      max_length: 20,
    })
    const field = makeField({ type: 'string', restrictions })
    expect(parse(field)).toMatchObject({
      choices: 'left, right, bilateral',
      maxLength: '20',
    })
  })

  it('enum: choices only, ignores max_length', () => {
    const restrictions = build('enum', {
      ...EMPTY_RESTRICTION_STATE,
      choices: 'a, b',
      maxLength: '20',
    })
    expect(restrictions).toEqual({ choices: ['a', 'b'] })
  })

  it('date: min/max as plain ISO date strings', () => {
    const restrictions = build('date', {
      ...EMPTY_RESTRICTION_STATE,
      minDate: '2020-01-01',
      maxDate: '2020-12-31',
    })
    expect(restrictions).toEqual({ min: '2020-01-01', max: '2020-12-31' })
    const field = makeField({ type: 'date', restrictions })
    expect(parse(field)).toMatchObject({
      minDate: '2020-01-01',
      maxDate: '2020-12-31',
    })
  })

  it('datetime: converts local input to UTC and back', () => {
    const local = '2020-06-15T10:30'
    const restrictions = build('datetime', {
      ...EMPTY_RESTRICTION_STATE,
      minDate: local,
      maxDate: local,
    })
    expect(restrictions).toEqual({
      min: datetimeLocalToUTC(local),
      max: datetimeLocalToUTC(local),
    })
    const field = makeField({ type: 'datetime', restrictions })
    const parsed = parse(field)
    expect(parsed.minDate).toBe(utcToDatetimeLocal(String(restrictions!.min)))
    expect(parsed.maxDate).toBe(utcToDatetimeLocal(String(restrictions!.max)))
  })

  it('file: accept and max_size', () => {
    const restrictions = build('file', {
      ...EMPTY_RESTRICTION_STATE,
      accept: '.csv,.txt',
      maxSize: '2048',
    })
    expect(restrictions).toEqual({ accept: '.csv,.txt', max_size: 2048 })
    const field = makeField({ type: 'file', restrictions })
    expect(parse(field)).toMatchObject({ accept: '.csv,.txt', maxSize: '2048' })
  })

  it('file_list: accept and max_size', () => {
    const restrictions = build('file_list', {
      ...EMPTY_RESTRICTION_STATE,
      accept: '.pdf',
      maxSize: '4096',
    })
    expect(restrictions).toEqual({ accept: '.pdf', max_size: 4096 })
  })

  it('reference: schema', () => {
    const restrictions = build('reference', {
      ...EMPTY_RESTRICTION_STATE,
      refSchema: 'Patient',
    })
    expect(restrictions).toEqual({ schema: 'Patient' })
    const field = makeField({ type: 'reference', restrictions })
    expect(parse(field)).toMatchObject({ refSchema: 'Patient' })
  })

  it('returns undefined when no restrictions are set', () => {
    expect(build('string', EMPTY_RESTRICTION_STATE)).toBeUndefined()
    expect(build('integer', EMPTY_RESTRICTION_STATE)).toBeUndefined()
    expect(build('boolean', EMPTY_RESTRICTION_STATE)).toBeUndefined()
  })

  it('parse on a field with no restrictions returns empty state', () => {
    expect(parse(makeField({ type: 'string', restrictions: {} }))).toEqual(
      EMPTY_RESTRICTION_STATE,
    )
  })
})

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

  it('stores the timezone and reads bounds in that zone', () => {
    const r = build('datetime', {
      ...EMPTY_RESTRICTION_STATE,
      timezone: CHI,
      minDate: '2024-03-01T15:30',
    })
    expect(r).toEqual({ timezone: CHI, min: '2024-03-01T21:30:00.000Z' })
  })

  it('round-trips through parse in the same zone', () => {
    const r = build('datetime', {
      ...EMPTY_RESTRICTION_STATE,
      timezone: CHI,
      minDate: '2024-07-01T15:30',
      maxDate: '2024-12-01T08:00',
    })
    const state = parse(makeField({ type: 'datetime', restrictions: r }))
    expect(state.timezone).toBe(CHI)
    expect(state.minDate).toBe('2024-07-01T15:30')
    expect(state.maxDate).toBe('2024-12-01T08:00')
  })

  it('omits timezone when inheriting', () => {
    expect(
      build('datetime', {
        ...EMPTY_RESTRICTION_STATE,
        minDate: '2024-03-01T15:30',
      }),
    ).not.toHaveProperty('timezone')
  })

  it('expresses input bounds in the effective zone', () => {
    const field = makeField({
      type: 'datetime',
      restrictions: { min: '2024-03-01T21:30:00Z' },
    })
    expect(toInputProps(field, CHI).minDate).toBe('2024-03-01T15:30')
    expect(toInputProps(field, 'UTC').minDate).toBe('2024-03-01T21:30')
  })

  it('flags a bound in a DST gap instead of storing a guess', () => {
    const state = {
      ...EMPTY_RESTRICTION_STATE,
      timezone: CHI,
      minDate: '2024-03-10T02:30',
    }
    expect(boundsProblem('datetime', state)).toMatch(/Not before/)
    expect(build('datetime', state)).toEqual({ timezone: CHI })
    expect(
      boundsProblem('datetime', { ...state, minDate: '2024-03-10T03:30' }),
    ).toBeNull()
    expect(boundsProblem('string', state)).toBeNull()
  })

  it('shows the zone in the summary', () => {
    expect(summarise({ timezone: CHI }, 'datetime')).toBe(`timezone ${CHI}`)
  })
})
