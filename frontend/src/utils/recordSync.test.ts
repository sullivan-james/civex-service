import { describe, it, expect } from 'vitest'
import { recordSyncText } from './recordSync'
import type { RecordSync } from '../api/records'

const base: RecordSync = {
  state: 'synced',
  remote: 'https://hub.example',
  pending: 0,
  seeding: 0,
  hub_seq: 4,
  synced_at: '2026-10-05T11:58:00Z',
  message: null,
  conflict_id: null,
  files: 0,
  files_waiting: 0,
}
const NOW = Date.parse('2026-10-05T12:00:00Z')

describe('recordSyncText', () => {
  it('says nothing with no authority, or when this project is one', () => {
    expect(recordSyncText({ ...base, state: 'not_connected' }, NOW)).toBeNull()
    expect(recordSyncText({ ...base, state: 'held_here' }, NOW)).toBeNull()
  })
  it('says synced with the server and when', () => {
    expect(recordSyncText(base, NOW)).toBe(
      'Synced with hub.example · 2 min ago',
    )
  })
  it('says what is waiting, refused or in conflict', () => {
    expect(recordSyncText({ ...base, state: 'pending', pending: 3 }, NOW)).toBe(
      'Waiting to send (3 changes)',
    )
    expect(
      recordSyncText(
        { ...base, state: 'refused', message: 'not allowed' },
        NOW,
      ),
    ).toBe('Refused: not allowed')
    expect(recordSyncText({ ...base, state: 'conflict' }, NOW)).toContain(
      'Conflict',
    )
    expect(recordSyncText({ ...base, state: 'first_upload' }, NOW)).toContain(
      'First upload',
    )
  })
  it('adds the files still to send', () => {
    expect(
      recordSyncText({ ...base, files: 5, files_waiting: 2 }, NOW),
    ).toContain('2 of 5 files not sent')
  })
})
