import { describe, it, expect } from 'vitest'
import { shownName } from './RecordFieldGrid'
import { formatSize } from '../../utils/storage'

describe('shownName', () => {
  it('prefers the resolved name, then the name, then a short hash', () => {
    const sha256 = 'abcdef0123456789'
    expect(
      shownName({ sha256, filename: 'a.wav', resolved_filename: 'b.wav' }),
    ).toBe('b.wav')
    expect(shownName({ sha256, filename: 'a.wav' })).toBe('a.wav')
    expect(shownName({ sha256, filename: '  ' })).toBe('abcdef01')
  })
})

describe('formatSize for attachments', () => {
  it('switches units at 1024', () => {
    expect(formatSize(452.8 * 1024)).toBe('453 KB')
    expect(formatSize(55707.6 * 1024)).toBe('54.4 MB')
    expect(formatSize(3 * 1024 ** 3)).toBe('3.0 GB')
  })
})
