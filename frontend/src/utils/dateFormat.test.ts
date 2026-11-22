import { afterEach, describe, expect, it } from 'vitest'
import {
  DATE_FORMATS,
  DEFAULT_DATE_FORMAT,
  datePlaceholder,
  formatDate,
  getDateFormat,
  parseDate,
  parseDateAtLeast,
  setDateFormat,
  subscribeDateFormat,
  type DateFormat,
} from './dateFormat'

afterEach(() => localStorage.clear())

// Each pattern at each precision: a day, a month, a year.
const WRITTEN: Record<DateFormat, [string, string, string]> = {
  'DD/MM/YYYY': ['14/06/2019', '06/2019', '2019'],
  'MM/DD/YYYY': ['06/14/2019', '06/2019', '2019'],
  'YYYY-MM-DD': ['2019-06-14', '2019-06', '2019'],
  'D MMM YYYY': ['14 Jun 2019', 'Jun 2019', '2019'],
}

describe('formatDate', () => {
  for (const format of DATE_FORMATS) {
    it(`writes a day, a month and a year as ${format}`, () => {
      const [day, month, year] = WRITTEN[format]
      expect(formatDate('2019-06-14', format)).toBe(day)
      expect(formatDate('2019-06', format)).toBe(month)
      expect(formatDate('2019', format)).toBe(year)
    })
  }

  it('drops the leading zero of a day only in D MMM YYYY', () => {
    expect(formatDate('2019-06-04', 'D MMM YYYY')).toBe('4 Jun 2019')
    expect(formatDate('2019-06-04', 'DD/MM/YYYY')).toBe('04/06/2019')
  })

  it('shows anything that is not a stored date as it is', () => {
    expect(formatDate('2019-02-30')).toBe('2019-02-30')
    expect(formatDate('soon')).toBe('soon')
    expect(formatDate('')).toBe('')
  })

  it('uses DD/MM/YYYY until another pattern is chosen', () => {
    expect(getDateFormat()).toBe(DEFAULT_DATE_FORMAT)
    expect(formatDate('2019-06-14')).toBe('14/06/2019')
    setDateFormat('MM/DD/YYYY')
    expect(formatDate('2019-06-14')).toBe('06/14/2019')
  })
})

describe('the chosen pattern', () => {
  it('is kept in the browser, and the default is not stored', () => {
    setDateFormat('D MMM YYYY')
    expect(localStorage.getItem('civex-date-format')).toBe('D MMM YYYY')
    expect(getDateFormat()).toBe('D MMM YYYY')
    setDateFormat(DEFAULT_DATE_FORMAT)
    expect(localStorage.getItem('civex-date-format')).toBeNull()
  })

  it('ignores a stored value it does not know', () => {
    localStorage.setItem('civex-date-format', 'YY.MM.DD')
    expect(getDateFormat()).toBe(DEFAULT_DATE_FORMAT)
  })

  it('tells subscribers when it changes', () => {
    let calls = 0
    const stop = subscribeDateFormat(() => calls++)
    setDateFormat('YYYY-MM-DD')
    stop()
    setDateFormat('MM/DD/YYYY')
    expect(calls).toBe(1)
  })
})

describe('parseDate', () => {
  for (const format of DATE_FORMATS) {
    it(`reads back what ${format} writes`, () => {
      const [day, month, year] = WRITTEN[format]
      expect(parseDate(day, format)).toBe('2019-06-14')
      expect(parseDate(month, format)).toBe('2019-06')
      expect(parseDate(year, format)).toBe('2019')
    })
    it(`reads an ISO date in ${format} too`, () => {
      expect(parseDate('2019-06-14', format)).toBe('2019-06-14')
      expect(parseDate('2019-06', format)).toBe('2019-06')
    })
  }

  it('takes other separators and one-digit days and months', () => {
    expect(parseDate('4.6.2019', 'DD/MM/YYYY')).toBe('2019-06-04')
    expect(parseDate('4-6-2019', 'DD/MM/YYYY')).toBe('2019-06-04')
    expect(parseDate('6/4/2019', 'MM/DD/YYYY')).toBe('2019-06-04')
    expect(parseDate('6 2019', 'DD/MM/YYYY')).toBe('2019-06')
  })

  it('reads month names, short or long, in D MMM YYYY', () => {
    expect(parseDate('4 June 2019', 'D MMM YYYY')).toBe('2019-06-04')
    expect(parseDate('4 jun. 2019', 'D MMM YYYY')).toBe('2019-06-04')
    expect(parseDate('September 2019', 'D MMM YYYY')).toBe('2019-09')
    expect(parseDate('4 Ju 2019', 'D MMM YYYY')).toBeNull()
    expect(parseDate('4 Foo 2019', 'D MMM YYYY')).toBeNull()
  })

  it('refuses what is not a real date', () => {
    expect(parseDate('31/02/2019', 'DD/MM/YYYY')).toBeNull()
    expect(parseDate('14/13/2019', 'DD/MM/YYYY')).toBeNull()
    expect(parseDate('13/14/2019', 'MM/DD/YYYY')).toBeNull()
    expect(parseDate('14/06/19', 'DD/MM/YYYY')).toBeNull() // two-digit year
    expect(parseDate('14/06/2019', 'YYYY-MM-DD')).toBeNull() // not its order
    expect(parseDate('14/06', 'DD/MM/YYYY')).toBeNull()
    expect(parseDate('next spring')).toBeNull()
    expect(parseDate('')).toBeNull()
    expect(parseDate('0000')).toBeNull()
  })

  it('holds a date to the precision a field needs', () => {
    expect(parseDateAtLeast('06/2019', 'day', 'DD/MM/YYYY')).toBeNull()
    expect(parseDateAtLeast('06/2019', 'month', 'DD/MM/YYYY')).toBe('2019-06')
    expect(parseDateAtLeast('2019', 'month', 'DD/MM/YYYY')).toBeNull()
    expect(parseDateAtLeast('2019', 'year', 'DD/MM/YYYY')).toBe('2019')
  })
})

describe('datePlaceholder', () => {
  it('names the forms a field takes in the pattern', () => {
    expect(datePlaceholder('day', 'DD/MM/YYYY')).toBe('DD/MM/YYYY')
    expect(datePlaceholder('month', 'YYYY-MM-DD')).toBe('YYYY-MM or YYYY-MM-DD')
    expect(datePlaceholder('year', 'D MMM YYYY')).toBe(
      'YYYY, MMM YYYY or D MMM YYYY',
    )
  })
})
