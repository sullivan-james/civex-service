import { describe, expect, it } from 'vitest'
import { EVERYTHING, can, notAllowed } from './permissions'

describe('permissions', () => {
  it('allows everything everywhere for the local user', () => {
    expect(can(EVERYTHING, 'write_records')).toBe(true)
    expect(can(EVERYTHING, 'delete', 'c1')).toBe(true)
  })

  it('limits an action to the collections named', () => {
    const allowed = { read: ['project'], write_records: ['collection:c1'] }
    expect(can(allowed, 'read')).toBe(true)
    expect(can(allowed, 'write_records', 'c1')).toBe(true)
    expect(can(allowed, 'write_records', 'c2')).toBe(false)
    // Asked with no collection: only a project-wide right says yes.
    expect(can(allowed, 'write_records')).toBe(false)
    expect(can(allowed, 'delete', 'c1')).toBe(false)
  })

  it('says why in one sentence, in the server’s words when it has them', () => {
    expect(notAllowed('delete')).toBe(
      'You may not delete records, collections and kinds of record here.',
    )
    expect(notAllowed('delete', { delete: 'remove things' })).toBe(
      'You may not remove things here.',
    )
  })
})
