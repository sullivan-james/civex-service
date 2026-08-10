import { describe, it, expect } from 'vitest'
import {
  parseFilenameByTokenFormat,
  extractCaptureGroup,
  normalizeNumericKey,
} from './filenamePattern'

describe('parseFilenameByTokenFormat', () => {
  it('parses a date-only token format', () => {
    expect(parseFilenameByTokenFormat('20240315', 'YYYYMMDD')).toBe(
      '2024-03-15',
    )
  })

  it('parses a datetime token format with a separator', () => {
    expect(
      parseFilenameByTokenFormat('20240315-091530', 'YYYYMMDD-HHmmSS'),
    ).toBe('2024-03-15T09:15:30')
  })

  it('treats non-token characters as raw regex, matching either separator', () => {
    const fmt = 'YYYYMMDD[-_]HHmmSS'
    expect(parseFilenameByTokenFormat('20240315-091530', fmt)).toBe(
      '2024-03-15T09:15:30',
    )
    expect(parseFilenameByTokenFormat('20240315_091530', fmt)).toBe(
      '2024-03-15T09:15:30',
    )
  })

  it('matches anywhere in the string, not just at the start', () => {
    expect(
      parseFilenameByTokenFormat('scan_20240315_raw.tiff', 'YYYYMMDD'),
    ).toBe('2024-03-15')
  })

  it('returns null when the format does not match', () => {
    expect(parseFilenameByTokenFormat('not-a-date', 'YYYYMMDD')).toBeNull()
  })
})

describe('extractCaptureGroup', () => {
  it('returns the first capture group when present', () => {
    expect(extractCaptureGroup('subject_042.tif', 'subject_(\\d+)')).toEqual({
      value: '042',
      error: null,
    })
  })

  it('falls back to the whole match when there is no capture group', () => {
    expect(extractCaptureGroup('subject_042.tif', '\\d+')).toEqual({
      value: '042',
      error: null,
    })
  })

  it('reports no match without throwing', () => {
    const result = extractCaptureGroup('no-digits-here.tif', 'subject_(\\d+)')
    expect(result.value).toBeNull()
    expect(result.error).toBe('No match in filename')
  })

  it('reports invalid regex without throwing', () => {
    const result = extractCaptureGroup('file.tif', '(unclosed')
    expect(result.value).toBeNull()
    expect(result.error).toMatch(/Invalid regex/)
  })

  it('returns nulls for an empty pattern', () => {
    expect(extractCaptureGroup('file.tif', '')).toEqual({
      value: null,
      error: null,
    })
  })
})

describe('normalizeNumericKey', () => {
  it('strips leading zeros from integer-looking keys', () => {
    expect(normalizeNumericKey('042')).toBe('42')
    expect(normalizeNumericKey('-007')).toBe('-7')
  })

  it('leaves non-integer keys unchanged', () => {
    expect(normalizeNumericKey('S042')).toBe('S042')
    expect(normalizeNumericKey('3.5')).toBe('3.5')
  })
})
