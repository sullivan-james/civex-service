import { describe, it, expect } from 'vitest'
import type { Transfer } from '../api/transfers'
import { describeTransfer, isBusy, queueAhead } from './transfers'

const t = (over: Partial<Transfer>): Transfer =>
  ({
    id: 'x',
    status: 'completed',
    auto_resume: false,
    created_at: null,
    ...over,
  }) as Transfer

describe('isBusy', () => {
  it('is true for a running, waiting, or drive-waiting move', () => {
    expect(isBusy(t({ status: 'running' }))).toBe(true)
    expect(isBusy(t({ status: 'queued' }))).toBe(true)
    expect(isBusy(t({ status: 'paused', auto_resume: true }))).toBe(true)
  })

  it('is false for one that is paused by a person or finished', () => {
    expect(isBusy(t({ status: 'paused' }))).toBe(false)
    expect(isBusy(t({ status: 'completed' }))).toBe(false)
    expect(isBusy(t({ status: 'interrupted' }))).toBe(false)
  })
})

describe('queueAhead', () => {
  it('counts the running move and every move waiting longer', () => {
    const ahead = queueAhead([
      t({ id: 'c', status: 'queued', created_at: '2026-10-04T10:02:00Z' }),
      t({ id: 'run', status: 'running' }),
      t({ id: 'a', status: 'queued', created_at: '2026-10-04T10:00:00Z' }),
      t({ id: 'b', status: 'queued', created_at: '2026-10-04T10:01:00Z' }),
      t({ id: 'old', status: 'completed' }),
    ])
    expect(ahead.get('a')).toBe(1)
    expect(ahead.get('b')).toBe(2)
    expect(ahead.get('c')).toBe(3)
    expect(ahead.has('run')).toBe(false)
    expect(ahead.has('old')).toBe(false)
  })

  it('is next in line (0 ahead) when nothing is running', () => {
    const ahead = queueAhead([t({ id: 'a', status: 'queued' })])
    expect(ahead.get('a')).toBe(0)
  })
})

describe('describeTransfer', () => {
  const files = (plan: { files: number; copied: number } | null) =>
    t({
      kind: 'files',
      spec: {
        kind: 'files',
        targets: ['vol-b'],
        sources: [],
        collection_ids: [],
        verify: 'copy',
        freeze_sources: false,
      },
      plan: plan as Transfer['plan'],
      progress: { files_total: 1519 } as Transfer['progress'],
    })

  it("counts a move of picked files from its plan, not the file list the server doesn't send", () => {
    expect(describeTransfer(files({ files: 1519, copied: 0 }))).toBe(
      'Move 1,519 files onto vol-b',
    )
    expect(describeTransfer(files(null), true)).toBe(
      'Moving 1,519 files to vol-b',
    )
  })

  it('says Copy when every file stays on its home drive too', () => {
    expect(describeTransfer(files({ files: 1519, copied: 1519 }))).toBe(
      'Copy 1,519 files onto vol-b',
    )
    expect(describeTransfer(files({ files: 10, copied: 4 }))).toBe(
      'Move 10 files onto vol-b (4 copied, not moved)',
    )
  })
})
