import { describe, expect, it } from 'vitest'
import {
  captureForDateFormat,
  dateFormats,
  describeDateFormat,
  describePattern,
  keyClashes,
  nameParts,
  placePattern,
  textBefore,
  textPattern,
  type PartChoice,
} from './patternFromExample'
import { parseFilenameByTokenFormat } from './filenamePattern'

function mark(name: string, part: string): [string, number, number] {
  const start = name.indexOf(part)
  return [name, start, start + part.length]
}

function captured(pattern: string, name: string): string | undefined {
  return new RegExp(pattern).exec(name)?.[1]
}

const one = (i: number, digitsOnly = false): PartChoice => ({
  from: i,
  to: i,
  digitsOnly,
})

describe('nameParts', () => {
  it('splits a name at spaces, dots, underscores and dashes', () => {
    expect(
      nameParts('20240611_dive07-hydro phone.wav').map((p) => p.text),
    ).toEqual(['20240611', 'dive07', 'hydro', 'phone', 'wav'])
  })
})

describe('placePattern', () => {
  it('takes the same part of names whose words differ', () => {
    const pattern = placePattern(one(1))
    expect(captured(pattern, 'Recording_A12_part3.wav')).toBe('A12')
    expect(captured(pattern, 'Take_B07_part1.wav')).toBe('B07')
  })

  it('takes the number inside a part, whatever the letters', () => {
    const pattern = placePattern(one(1, true))
    expect(captured(pattern, 'Recording_A12_part3.wav')).toBe('12')
    expect(captured(pattern, 'Take_B7_part1.wav')).toBe('7')
  })

  it('takes a run of parts with what separates them', () => {
    const pattern = placePattern({ from: 1, to: 2, digitsOnly: false })
    expect(captured(pattern, 'x_2024-06_y.csv')).toBe('2024-06')
  })

  it('takes the first part from the start', () => {
    expect(captured(placePattern(one(0)), '42_notes.txt')).toBe('42')
  })

  it.each(['a.b (copy).txt', 'report[3].pdf', 'tag+v2.txt'])(
    'is a valid pattern for %s',
    (name) => {
      for (let i = 0; i < nameParts(name).length; i++)
        expect(captured(placePattern(one(i)), name)).toBe(
          nameParts(name)[i].text,
        )
    },
  )
})

describe('textPattern', () => {
  it('finds the number after the same word, wherever it is', () => {
    const name = '20240611_dive07_hydrophone.wav'
    const parts = nameParts(name)
    expect(textBefore(name, parts, one(1, true))).toBe('dive')
    const pattern = textPattern(name, parts, one(1, true))!
    expect(captured(pattern, 'extra_20240612_dive163_x.wav')).toBe('163')
  })

  it('uses the part before when nothing in the part leads it', () => {
    const name = 'site_A_2024.csv'
    const parts = nameParts(name)
    expect(textBefore(name, parts, one(1))).toBe('site_')
    expect(captured(textPattern(name, parts, one(1))!, 'x_site_B_1.csv')).toBe(
      'B',
    )
  })

  it('is null when nothing comes before', () => {
    const parts = nameParts('42_notes.txt')
    expect(textPattern('42_notes.txt', parts, one(0))).toBeNull()
  })

  it('escapes what it copies', () => {
    const name = 'a+b_7.txt'
    const parts = nameParts(name)
    expect(captured(textPattern(name, parts, one(1))!, 'a+b_9.txt')).toBe('9')
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

describe('describePattern', () => {
  it.each([
    [placePattern(one(1)), 'the second part of the name'],
    [placePattern(one(0)), 'the first part of the name'],
    [placePattern(one(2, true)), 'the number in the third part of the name'],
    [
      placePattern({ from: 1, to: 2, digitsOnly: false }),
      'parts 2 to 3 of the name',
    ],
    ['dive([0-9]+)', 'the number after “dive”'],
    ['site_([^ ._-]+)', 'the part after “site_”'],
    ['a\\+b_([^ ._-]+)', 'the part after “a+b_”'],
  ])('%s', (pattern, words) => {
    expect(describePattern(pattern)).toBe(words)
  })

  it('says nothing of a pattern written by hand', () => {
    expect(describePattern('sel_(\\d{2})')).toBeNull()
  })
})
