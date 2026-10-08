import { describe, expect, it } from 'vitest'
import {
  formatsFor,
  insertAt,
  removeVariable,
  sampleValue,
  setVariableFormat,
  variablesIn,
} from './templates'

describe('variablesIn', () => {
  it('finds variables with and without formats, in order', () => {
    const vars = variablesIn('{site}-{taken_on:YYYY-MM}')
    expect(vars.map((v) => [v.name, v.spec])).toEqual([
      ['site', null],
      ['taken_on', 'YYYY-MM'],
    ])
  })

  it('skips escaped braces and tolerates an unclosed one', () => {
    expect(variablesIn('{{x}} {a')).toEqual([])
    expect(variablesIn('{{x}} {a}').map((v) => v.name)).toEqual(['a'])
  })
})

describe('setVariableFormat', () => {
  it('sets, replaces and removes a format on one variable', () => {
    expect(setVariableFormat('{a}-{b}', 1, 'upper')).toBe('{a}-{b:upper}')
    expect(setVariableFormat('{a}-{b:upper}', 1, 'lower')).toBe('{a}-{b:lower}')
    expect(setVariableFormat('{a}-{b:upper}', 1, null)).toBe('{a}-{b}')
  })

  it('leaves the template alone for an unknown index', () => {
    expect(setVariableFormat('{a}', 3, 'upper')).toBe('{a}')
  })
})

describe('insertAt', () => {
  it('writes over the selection and moves the cursor after it', () => {
    expect(insertAt('ab-cd', 2, 3, '{x}')).toEqual({
      value: 'ab{x}cd',
      cursor: 5,
    })
  })
})

describe('formats and samples', () => {
  it('offers date formats for dates and none for geometry', () => {
    expect(formatsFor('date').map((f) => f.spec)).toContain('YYYY-MM')
    expect(formatsFor('geo')).toHaveLength(1)
  })

  it('samples a value of the right type', () => {
    expect(sampleValue('integer', 'n')).toBe(7)
    expect(sampleValue('string', 'Site')).toBe('Site')
  })
})

describe('removeVariable', () => {
  it('drops a variable with the separator before it', () => {
    expect(removeVariable('{a}_{b}_{c}', 1)).toBe('{a}_{c}')
    expect(removeVariable('{a} - {b}', 1)).toBe('{a}')
  })

  it('drops the separator after the first variable', () => {
    expect(removeVariable('{a}_{b}', 0)).toBe('{b}')
    expect(removeVariable('{a}', 0)).toBe('')
  })

  it('leaves the template alone for an unknown index', () => {
    expect(removeVariable('{a}', 3)).toBe('{a}')
  })
})
