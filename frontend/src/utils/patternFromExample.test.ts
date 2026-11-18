import { describe, expect, it } from 'vitest'
import {
  captureForDateFormat,
  dateFormats,
  describeDateFormat,
  keyClashes,
  keyPattern,
} from './patternFromExample'
import { parseFilenameByTokenFormat } from './filenamePattern'

function mark(name: string, part: string): [string, number, number] {
  const start = name.indexOf(part)
  return [name, start, start + part.length]
}

function captured(pattern: string, name: string): string | undefined {
  return new RegExp(pattern).exec(name)?.[1]
}

describe('keyPattern', () => {
  it.each([
    ['sel_07_contour.csv', '07', 'sel_([0-9]+)'],
    ['rec2024_site-A_07.csv', '07', '_site-A_([0-9]+)'],
  ])('%s marking %s', (name, part, expected) => {
    const pattern = keyPattern(...mark(name, part))
    expect(pattern).toBe(expected)
    expect(captured(pattern, name)).toBe(part)
  })

  it.each([
    ['site-ABC_2024.wav', 'ABC'],
    ['take12b.wav', '12b'],
    ['42_notes.txt', '42'],
    ['x107_y.csv', '07'],
    ['a.b (copy).txt', 'b (copy)'],
    ['tag+v2.txt', 'v2'],
    ['report[3].pdf', '3'],
  ])('captures exactly the marked part of %s', (name, part) => {
    const pattern = keyPattern(...mark(name, part))
    expect(captured(pattern, name)).toBe(part)
  })

  it('reads other names written the same way', () => {
    const pattern = keyPattern(...mark('sel_07_contour.csv', '07'))
    expect(captured(pattern, 'sel_163_contour.csv')).toBe('163')
  })

  it('is blank when nothing is marked', () => {
    expect(keyPattern('abc', 1, 1)).toBe('')
  })
})

describe('dateFormats', () => {
  it.each([
    ['rec_20240611-142233.wav', '20240611-142233', 'YYYYMMDD[-_]HHmmSS'],
    ['rec_20240611.wav', '20240611', 'YYYYMMDD'],
    ['2024-06-11 notes', '2024-06-11', 'YYYY[-_]MM[-_]DD'],
    ['x20240611T142233', '20240611T142233', 'YYYYMMDDTHHmmSS'],
    ['20240611142233.wav', '20240611142233', 'YYYYMMDDHHmmSS'],
  ])('%s', (name, part, expected) => {
    const formats = dateFormats(...mark(name, part), 'datetime')
    expect(formats[0]).toBe(expected)
    expect(parseFilenameByTokenFormat(name, formats[0])).not.toBeNull()
  })

  it('offers day first and month first when both fit', () => {
    expect(dateFormats(...mark('a_11-06-2024', '11-06-2024'), 'date')).toEqual([
      'DD[-_]MM[-_]YYYY',
      'MM[-_]DD[-_]YYYY',
    ])
  })

  it('offers only what is a real date', () => {
    expect(dateFormats(...mark('a_25-06-2024', '25-06-2024'), 'date')).toEqual([
      'DD[-_]MM[-_]YYYY',
    ])
    expect(dateFormats(...mark('a_20241399', '20241399'), 'date')).toEqual([])
    expect(dateFormats(...mark('abc', 'abc'), 'date')).toEqual([])
  })

  it('leaves the time out of a date', () => {
    expect(
      dateFormats(...mark('20240611-142233', '20240611-142233'), 'date')[0],
    ).toBe('YYYYMMDD')
  })

  it('escapes other separators', () => {
    expect(dateFormats(...mark('2024.06.11', '2024.06.11'), 'date')[0]).toBe(
      'YYYY\\.MM\\.DD',
    )
  })
})

describe('captureForDateFormat', () => {
  it('turns tokens into digits', () => {
    expect(captureForDateFormat('YYYYMMDD[-_]HHmmSS')).toBe(
      '([0-9]{8}[-_][0-9]{6})',
    )
    const capture = captureForDateFormat('YYYY\\.MM\\.DD')
    expect(captured(capture, 'x_2024.06.11.wav')).toBe('2024.06.11')
  })
})

describe('describeDateFormat', () => {
  it('says the date in words', () => {
    expect(describeDateFormat('20240611-142233', 'YYYYMMDD[-_]HHmmSS')).toBe(
      '11 June 2024 14:22:33 (year first)',
    )
    expect(describeDateFormat('11-06-2024', 'DD[-_]MM[-_]YYYY')).toBe(
      '11 June 2024 (day first)',
    )
  })
})

describe('keyClashes', () => {
  it('groups names that give the same key', () => {
    const clashes = keyClashes([
      { filename: 'sel_07.csv', value: '07' },
      { filename: 'sel_7.csv', value: '7' },
      { filename: 'sel_8.csv', value: '8' },
      { filename: 'other.csv', value: null },
    ])
    expect([...clashes]).toEqual([['7', ['sel_07.csv', 'sel_7.csv']]])
  })
})
