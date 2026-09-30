import { describe, it, expect } from 'vitest'
import { viewNameError } from './naming'

describe('viewNameError', () => {
  it("accepts names in the user's own words", () => {
    for (const ok of [
      'Missing selection table',
      'Needs review (QC) – 2026',
      'Étude #2: 50% done?',
      'snake_case_still_fine',
    ])
      expect(viewNameError(ok)).toBeNull()
  })

  it('only refuses what cannot sit in a URL path, or is empty', () => {
    expect(viewNameError('   ')).toMatch(/required/)
    expect(viewNameError('a/b')).toMatch(/can't contain/)
    expect(viewNameError('a\\b')).toMatch(/can't contain/)
    expect(viewNameError('..')).toMatch(/only dots/)
    expect(viewNameError('x'.repeat(300))).toMatch(/too long/)
  })
})
