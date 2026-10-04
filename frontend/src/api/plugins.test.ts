import { describe, it, expect } from 'vitest'
import { configType } from './plugins'

describe('configType', () => {
  it('is the key own type', () => {
    expect(configType({ type: 'string' })).toBe('string')
  })

  it('is the real type of an optional one, not "any"', () => {
    // `delimiters: list[str] | None` in a plugin's config schema.
    expect(configType({ anyOf: [{ type: 'array' }, { type: 'null' }] })).toBe(
      'array',
    )
  })

  it('lists the types a key may be, without null', () => {
    expect(
      configType({
        anyOf: [{ type: 'string' }, { type: 'integer' }, { type: 'null' }],
      }),
    ).toBe('string | integer')
  })

  it('is "any" when the schema says nothing', () => {
    expect(configType({})).toBe('any')
  })
})
