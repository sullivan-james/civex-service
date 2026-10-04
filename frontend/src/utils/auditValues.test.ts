import { describe, it, expect } from 'vitest'
import { changeLabel, valueText } from './auditValues'

describe('valueText', () => {
  it('shows blanks as (none)', () => {
    expect(valueText(null)).toBe('(none)')
    expect(valueText('')).toBe('(none)')
    expect(valueText([])).toBe('(none)')
  })

  it('shows a file by its name and a list joined', () => {
    expect(valueText({ sha256: 'a', filename: 'x.pdf', size: 1 })).toBe('x.pdf')
    expect(valueText(['a', 'b'])).toBe('a, b')
  })

  it('never prints [object Object]', () => {
    expect(valueText({ min: 1, max: 5 })).toBe('{"min":1,"max":5}')
  })

  it('keeps false and zero', () => {
    expect(valueText(false)).toBe('false')
    expect(valueText(0)).toBe('0')
  })
})

describe('changeLabel', () => {
  it('prefers the field label', () => {
    expect(changeLabel({ field: 'age', label: 'Age in years' })).toBe(
      'Age in years',
    )
  })

  it('reads a renamed field from its name', () => {
    expect(changeLabel({ field: 'blood_type', label: null })).toBe('Blood Type')
  })

  it('names schema attributes', () => {
    expect(changeLabel({ field: 'display_template', label: null })).toBe(
      'Record name',
    )
  })
})
