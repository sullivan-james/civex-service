import { describe, it, expect } from 'vitest'
import { parseCsv } from './csv'

describe('parseCsv', () => {
  it('parses a simple CSV into columns and rows', () => {
    const result = parseCsv('name,age\nAda,36\nGrace,85\n')
    expect(result.columns).toEqual(['name', 'age'])
    expect(result.rows).toEqual([
      { name: 'Ada', age: '36' },
      { name: 'Grace', age: '85' },
    ])
  })

  it('handles quoted fields containing commas and newlines', () => {
    const result = parseCsv('name,note\n"Lovelace, Ada","multi\nline"\n')
    expect(result.rows).toEqual([
      { name: 'Lovelace, Ada', note: 'multi\nline' },
    ])
  })

  it('handles escaped double quotes inside a quoted field', () => {
    const result = parseCsv('name\n"She said ""hi"""\n')
    expect(result.rows).toEqual([{ name: 'She said "hi"' }])
  })

  it('handles CRLF line endings', () => {
    const result = parseCsv('a,b\r\n1,2\r\n')
    expect(result.rows).toEqual([{ a: '1', b: '2' }])
  })

  it('handles a file with no trailing newline', () => {
    const result = parseCsv('a,b\n1,2')
    expect(result.rows).toEqual([{ a: '1', b: '2' }])
  })

  it('pads missing trailing fields with empty strings', () => {
    const result = parseCsv('a,b,c\n1,2\n')
    expect(result.rows).toEqual([{ a: '1', b: '2', c: '' }])
  })

  it('returns empty columns/rows for empty input', () => {
    expect(parseCsv('')).toEqual({ columns: [], rows: [] })
  })
})
