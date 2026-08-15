import { describe, it, expect } from 'vitest'
import { suggestFieldMapping, inferColumnType } from './importMapping'
import type { Field } from '../api/schemas'

function field(name: string, label: string | null = null): Field {
  return {
    id: name,
    name,
    label,
    type: 'string',
    required: false,
    restrictions: {},
    default: null,
    position: null,
  }
}

describe('suggestFieldMapping', () => {
  it('matches columns to fields by normalized name', () => {
    const fields = [field('recording_date'), field('site_id')]
    const mapping = suggestFieldMapping(
      ['Recording Date', 'Site ID', 'Notes'],
      fields,
    )
    expect(mapping).toEqual({
      'Recording Date': 'recording_date',
      'Site ID': 'site_id',
      Notes: null,
    })
  })

  it('matches columns to fields by label when the name differs', () => {
    const fields = [field('rd', 'Recording Date')]
    const mapping = suggestFieldMapping(['recording date'], fields)
    expect(mapping).toEqual({ 'recording date': 'rd' })
  })

  it('does not map the same field to two columns', () => {
    const fields = [field('id')]
    const mapping = suggestFieldMapping(['id', 'ID'], fields)
    const mapped = Object.values(mapping).filter((v) => v === 'id')
    expect(mapped).toHaveLength(1)
  })
})

describe('inferColumnType', () => {
  it('infers integer for whole-number strings', () => {
    expect(inferColumnType(['1', '2', '-3'])).toBe('integer')
  })

  it('infers float when a decimal point appears', () => {
    expect(inferColumnType(['1.5', '2', '-3.25'])).toBe('float')
  })

  it('infers boolean for true/false strings', () => {
    expect(inferColumnType(['true', 'False', 'TRUE'])).toBe('boolean')
  })

  it('infers date for ISO date strings', () => {
    expect(inferColumnType(['2024-01-01', '2024-03-15'])).toBe('date')
  })

  it('infers datetime for parseable timestamps', () => {
    expect(
      inferColumnType(['2024-01-01T09:00:00Z', '2024-03-15T10:00:00Z']),
    ).toBe('datetime')
  })

  it('falls back to string for mixed or empty values', () => {
    expect(inferColumnType(['1', 'abc'])).toBe('string')
    expect(inferColumnType(['', ' '])).toBe('string')
  })
})
