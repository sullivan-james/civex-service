import { describe, expect, it } from 'vitest'
import type { Transfer } from '../api/transfers'
import { someEnded } from './useTransfers'

const t = (id: string, status: Transfer['status']): Transfer =>
  ({ id, status, auto_resume: false }) as Transfer

describe('someEnded', () => {
  it('is true once a move that was running has stopped, so sizes are asked again', () => {
    expect(someEnded([t('a', 'running')], [t('a', 'completed')])).toBe(true)
    expect(someEnded([t('a', 'queued')], [t('a', 'cancelled')])).toBe(true)
  })

  it('is false while it runs, on the first look, and for moves long finished', () => {
    expect(someEnded([t('a', 'running')], [t('a', 'running')])).toBe(false)
    expect(someEnded(undefined, [t('a', 'completed')])).toBe(false)
    expect(someEnded([t('a', 'completed')], [t('a', 'completed')])).toBe(false)
  })
})
