import { describe, it, expect } from 'vitest'
import {
  extractFromFilename,
  firstFilename,
  fromFilenameRule,
  patternProblem,
  previewFromFilename,
} from './filenameExtract'
import type { Field } from '../api/schemas'

// The same table as `tests/services/test_from_filename.py`: the two sides
// must read a name the same way.
describe('extractFromFilename mirrors the server', () => {
  it.each<[string | string[], string, string, unknown]>([
    ['site-([A-Z]+)_', 'string', 'site-NR_2024.jpg', 'NR'],
    ['\\d+', 'integer', 'take_042.wav', 42],
    ['depth_([\\d.]+)m', 'float', 'depth_12.5m.csv', 12.5],
    ['YYYY-MM-DD', 'date', 'site-NR_2024-03-15.jpg', '2024-03-15'],
    [
      'YYYYMMDD[-_]HHmmSS',
      'datetime',
      '20240315_093000.wav',
      '2024-03-15T09:30:00',
    ],
    ['take_(\\d+)', 'integer', 'nothing_here.wav', null],
    // Named groups: the parts in any order, any width.
    [
      '(?P<day>\\d{2})\\.(?P<month>\\d{2})\\.(?P<year>\\d{4})',
      'date',
      'scan_15.03.2024.pdf',
      '2024-03-15',
    ],
    [
      '(?P<year>\\d{4})(?P<month>\\d{2})(?P<day>\\d{2})T(?P<hour>\\d{1,2})h',
      'datetime',
      '20240315T9h.csv',
      '2024-03-15T09:00:00',
    ],
    // Several patterns: the first that matches wins.
    [
      ['DDMMYYYY_HHmmSS', 'YYYY-MM-DD'],
      'datetime',
      '15032024_093000.csv',
      '2024-03-15T09:30:00',
    ],
    [
      ['DDMMYYYY_HHmmSS', 'YYYY-MM-DD'],
      'datetime',
      'site_2024-03-15.csv',
      '2024-03-15T00:00:00',
    ],
    [['take_(\\d+)', 'sel_(\\d+)'], 'integer', 'sel_12.txt', 12],
    [['take_(\\d+)', 'sel_(\\d+)'], 'integer', 'other.txt', null],
  ])('%s on a %s reads %s', (pattern, kind, filename, expected) => {
    expect(extractFromFilename(filename, pattern, kind)).toEqual({
      value: expected,
      error: null,
    })
  })

  it('refuses what cannot work', () => {
    expect(patternProblem('(', 'string')).toMatch(/regular expression/)
    expect(patternProblem('', 'string')).toMatch(/empty/)
    expect(patternProblem('YYYYMMDD', 'string')).toBeNull()
    expect(patternProblem('HHmmSS', 'datetime')).toMatch(/YYYY MM DD/)
    expect(patternProblem('YYYY-MM', 'date')).toMatch(/DD/)
    expect(patternProblem('(\\d+)', 'boolean')).toMatch(/can't be filled/)
    expect(patternProblem('(?P<year>\\d{4})', 'date')).toMatch(
      /needs month, day/,
    )
    expect(
      patternProblem(
        '(?P<year>\\d{4})(?P<month>\\d{2})(?P<day>\\d{2})(?P<week>\\d)',
        'date',
      ),
    ).toMatch(/unknown group\(s\) week/)
    // A list is checked pattern by pattern.
    expect(
      extractFromFilename('x.csv', ['a(\\d+)', '('], 'integer').error,
    ).toMatch(/regular expression/)
  })

  it('a match that is not the type is an error', () => {
    expect(
      extractFromFilename('take_ab.wav', 'take_(\\w+)', 'integer').error,
    ).toMatch(/not a whole number/)
    expect(
      extractFromFilename('x_20241399.wav', 'YYYYMMDD', 'date').error,
    ).toMatch(/not a date/)
  })

  it('reads a file or the first of a list', () => {
    expect(firstFilename({ filename: 'a.wav' })).toBe('a.wav')
    expect(firstFilename([{ filename: 'a.wav' }, { filename: 'b' }])).toBe(
      'a.wav',
    )
    expect(firstFilename([])).toBeNull()
    expect(firstFilename(undefined)).toBeNull()
    expect(firstFilename('a.wav')).toBeNull()
  })

  it('reads a rule with one pattern or several', () => {
    expect(
      fromFilenameRule({ from_filename: { field: 'a', pattern: 'p' } }),
    ).toEqual({ field: 'a', patterns: ['p'] })
    expect(
      fromFilenameRule({ from_filename: { field: 'a', pattern: ['p', 'q'] } }),
    ).toEqual({ field: 'a', patterns: ['p', 'q'] })
    expect(fromFilenameRule({ from_filename: 'a' })).toBeNull()
    expect(fromFilenameRule({})).toBeNull()
    expect(fromFilenameRule(undefined)).toBeNull()
  })
})

describe('previewFromFilename', () => {
  const take = {
    name: 'take',
    type: 'integer',
    restrictions: { from_filename: { field: 'audio', pattern: '_t(\\d+)' } },
  } as unknown as Field

  it('says what a blank field will get from the file attached', () => {
    expect(
      previewFromFilename(take, { audio: { filename: 'rec_t3.wav' } }),
    ).toEqual({
      filename: 'rec_t3.wav',
      result: { value: 3, error: null },
    })
  })

  it('is quiet with no file, a typed value, or no rule', () => {
    expect(previewFromFilename(take, {})).toBeNull()
    expect(
      previewFromFilename(take, { audio: { filename: 'rec_t3.wav' }, take: 9 }),
    ).toBeNull()
    expect(
      previewFromFilename({ ...take, restrictions: {} } as unknown as Field, {
        audio: { filename: 'rec_t3.wav' },
      }),
    ).toBeNull()
  })
})
