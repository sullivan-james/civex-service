import { describe, it, expect, vi, afterEach } from 'vitest'
import { QueryClient } from '@tanstack/react-query'
import {
  downloadFiles,
  moveFiles,
  moveThenOpen,
  type FlowContext,
} from './fileFlows'
import { exported, fakeServer, json, plan, transfer } from './testSupport'

afterEach(() => vi.unstubAllGlobals())

const SELECTION = { collection: 'hb', schema_name: 'selection' }

function context() {
  const toast = { success: vi.fn(), error: vi.fn(), info: vi.fn() }
  const problem = vi.fn()
  const ctx: FlowContext = {
    toast,
    problem,
    qc: new QueryClient(),
    pollMs: 0,
  }
  return { ctx, toast, problem }
}

const gather = { transfer_id: 't1', volume: 'archive', files: 3, bytes: 3000 }

describe('moving, then opening', () => {
  it('waits for the move, then links and opens', async () => {
    const polls = [
      transfer({ status: 'queued' }),
      transfer({ status: 'running' }),
      transfer({ status: 'completed' }),
    ]
    const calls = fakeServer({
      '/api/file-access/gather': gather,
      '/api/store/transfers/t1': () => json(polls.shift()),
      '/api/file-access/export': exported({ location: 'archive' }),
    })
    const { ctx, toast } = context()

    await moveThenOpen(ctx, SELECTION, 'hb', 'archive')

    expect(calls.map((c) => c.path)).toEqual([
      '/api/file-access/gather',
      '/api/store/transfers/t1',
      '/api/store/transfers/t1',
      '/api/store/transfers/t1',
      '/api/file-access/export',
    ])
    expect(calls[4].body).toMatchObject({ mode: 'link', allow_partial: true })
    expect(toast.success).toHaveBeenCalledOnce()
    expect(toast.error).not.toHaveBeenCalled()
  })

  it('does not open a folder when the move was paused, and says what to do', async () => {
    const calls = fakeServer({
      '/api/file-access/gather': gather,
      '/api/store/transfers/t1': () => json(transfer({ status: 'paused' })),
    })
    const { ctx, toast } = context()

    await moveThenOpen(ctx, SELECTION, 'hb', 'archive')

    expect(calls.map((c) => c.path)).not.toContain('/api/file-access/export')
    expect(toast.error).toHaveBeenCalledWith(
      expect.stringMatching(/was paused.*Resume it in Settings/i),
    )
  })

  it('keeps waiting while a move is only paused for a drive to come back', async () => {
    const polls = [
      transfer({ status: 'paused', auto_resume: true }),
      transfer({ status: 'completed' }),
    ]
    const calls = fakeServer({
      '/api/file-access/gather': gather,
      '/api/store/transfers/t1': () => json(polls.shift()),
      '/api/file-access/export': exported(),
    })
    const { ctx, toast } = context()

    await moveThenOpen(ctx, SELECTION, 'hb', 'archive')

    expect(calls.map((c) => c.path)).toContain('/api/file-access/export')
    expect(toast.error).not.toHaveBeenCalled()
  })

  it('says so when the move failed', async () => {
    fakeServer({
      '/api/file-access/gather': gather,
      '/api/store/transfers/t1': () => json(transfer({ status: 'failed' })),
    })
    const { ctx, toast } = context()

    await moveThenOpen(ctx, SELECTION, 'hb', 'archive')

    expect(toast.error).toHaveBeenCalledWith(
      expect.stringMatching(/ended \(failed\)/),
    )
  })

  it('goes back to the dialog if something changed while it moved', async () => {
    fakeServer({
      '/api/file-access/gather': gather,
      '/api/store/transfers/t1': () => json(transfer()),
      '/api/file-access/export': () =>
        json(
          {
            detail: 'These files are on 2 drives',
            code: 'files_scattered',
            plan: plan({ scattered: true }),
          },
          409,
        ),
    })
    const { ctx, problem } = context()

    await moveThenOpen(ctx, SELECTION, 'hb', 'archive')

    expect(problem).toHaveBeenCalledWith(
      expect.objectContaining({ kind: 'open' }),
    )
  })

  it('reports a move that could not even be started', async () => {
    fakeServer({
      '/api/file-access/gather': () =>
        json({ detail: 'Every reachable file is already on archive.' }, 422),
    })
    const { ctx, toast } = context()

    await moveThenOpen(ctx, SELECTION, 'hb', 'archive')

    expect(toast.error).toHaveBeenCalledWith(
      expect.stringMatching(/already on archive/),
    )
  })
})

// -- showing how far it has got ---------------------------------------------------------

import { renderHook } from '@testing-library/react'
import { useFileJobs } from '../../hooks/fileJobs'
import { chooseCopy, openAsFolder } from './fileFlows'

/** A request that stays open until released, so there is something to follow. */
function gate() {
  let open!: () => void
  const wait = new Promise<void>((r) => (open = r))
  return { wait, open }
}

describe('following a request while it runs', () => {
  it('tags the request with an id and asks how far it has got by that id', async () => {
    const g = gate()
    const calls = fakeServer({
      '/api/file-access/export': async () => {
        await g.wait
        return json(exported())
      },
      '/api/file-access/progress': () => json({ phase: '', done: 0, total: 0 }),
    })
    const { ctx } = context()
    ctx.progressMs = 5

    const running = openAsFolder(ctx, SELECTION, 'hb')
    await vi.waitFor(() =>
      expect(
        calls.some((c) => c.path.startsWith('/api/file-access/progress/')),
      ).toBe(true),
    )
    g.open()
    await running

    const sent = calls.find((c) => c.path === '/api/file-access/export')!
    const id = sent.headers['x-civex-progress']
    expect(id).toMatch(/^[A-Za-z0-9_-]{8,64}$/)
    // The same id is the one asked about.
    const asked = calls.filter((c) =>
      c.path.startsWith('/api/file-access/progress/'),
    )
    expect(
      asked.every((c) => c.path === `/api/file-access/progress/${id}`),
    ).toBe(true)
  })

  it('shows the stage and a bar on the job as the server reports it', async () => {
    const g = gate()
    fakeServer({
      '/api/file-access/export': async () => {
        await g.wait
        return json(exported())
      },
      '/api/file-access/progress': () =>
        json({
          phase: 'Finding files',
          done: 12000,
          total: 40000,
          finished: false,
        }),
    })
    const { ctx } = context()
    ctx.progressMs = 5
    const jobs = renderHook(() => useFileJobs())

    const running = openAsFolder(ctx, SELECTION, 'hb')
    await vi.waitFor(() =>
      expect(jobs.result.current[0]?.detail).toBe('Finding files'),
    )

    expect(jobs.result.current[0].progress).toEqual({
      fraction: 0.3,
      label: 'Finding files',
      count: '12,000 of 40,000',
    })
    g.open()
    await running
    expect(jobs.result.current).toEqual([])
  })

  it('shows just the stage while the number of steps is not known yet', async () => {
    const g = gate()
    fakeServer({
      '/api/file-access/export': async () => {
        await g.wait
        return json(exported())
      },
      '/api/file-access/progress': () =>
        json({ phase: 'Working out the folders', done: 0, total: 0 }),
    })
    const { ctx } = context()
    ctx.progressMs = 5
    const jobs = renderHook(() => useFileJobs())

    const running = openAsFolder(ctx, SELECTION, 'hb')
    await vi.waitFor(() =>
      expect(jobs.result.current[0]?.detail).toBe('Working out the folders'),
    )

    expect(jobs.result.current[0].progress).toBeUndefined()
    g.open()
    await running
  })

  it('never shows more than all of it', async () => {
    const g = gate()
    fakeServer({
      '/api/file-access/export': async () => {
        await g.wait
        return json(exported())
      },
      '/api/file-access/progress': () =>
        json({ phase: 'x', done: 90, total: 50 }),
    })
    const { ctx } = context()
    ctx.progressMs = 5
    const jobs = renderHook(() => useFileJobs())

    const running = openAsFolder(ctx, SELECTION, 'hb')
    await vi.waitFor(() =>
      expect(jobs.result.current[0]?.progress).toBeTruthy(),
    )

    expect(jobs.result.current[0].progress?.fraction).toBe(1)
    g.open()
    await running
  })

  it('carries on when the server has not begun reporting yet', async () => {
    const g = gate()
    const calls = fakeServer({
      '/api/file-access/export': async () => {
        await g.wait
        return json(exported())
      },
      '/api/file-access/progress': () =>
        json({ detail: 'Nothing is reporting' }, 404),
    })
    const { ctx, toast } = context()
    ctx.progressMs = 5

    const running = openAsFolder(ctx, SELECTION, 'hb')
    await vi.waitFor(() =>
      expect(
        calls.filter((c) => c.path.includes('/progress/')).length,
      ).toBeGreaterThan(1),
    )
    g.open()
    await running

    expect(toast.error).not.toHaveBeenCalled()
    expect(toast.success).toHaveBeenCalledOnce()
  })

  it('stops asking once the request is over', async () => {
    const calls = fakeServer({
      '/api/file-access/export': exported(),
      '/api/file-access/progress': () =>
        json({ phase: 'x', done: 1, total: 2 }),
    })
    const { ctx } = context()
    ctx.progressMs = 5

    await openAsFolder(ctx, SELECTION, 'hb')
    const after = calls.length
    await new Promise((r) => setTimeout(r, 40))

    expect(calls.length).toBe(after)
  })

  it('also follows a plan made to choose a drive to copy to', async () => {
    const calls = fakeServer({
      '/api/file-access/plan': plan(),
      '/api/file-access/progress': () =>
        json({ phase: 'x', done: 0, total: 0 }),
    })
    const { ctx, problem } = context()

    await chooseCopy(ctx, SELECTION)

    expect(calls[0].headers['x-civex-progress']).toMatch(
      /^[A-Za-z0-9_-]{8,64}$/,
    )
    expect(problem).toHaveBeenCalledWith(
      expect.objectContaining({ kind: 'copy' }),
    )
  })

  it('sends the tag with the body still understood as JSON', async () => {
    const calls = fakeServer({ '/api/file-access/export': exported() })
    const { ctx } = context()

    await openAsFolder(ctx, SELECTION, 'hb')

    const sent = calls.find((c) => c.path === '/api/file-access/export')!
    expect(sent.headers['content-type']).toBe('application/json')
    expect(sent.body).toMatchObject({ collection: 'hb', mode: 'link' })
  })
})

describe('moving and downloading picked files', () => {
  it('moves the picked files, following the move to the end', async () => {
    const calls = fakeServer({
      '/api/file-access/gather': gather,
      '/api/store/transfers/t1': () => json(transfer({ status: 'completed' })),
    })
    const { ctx, toast } = context()

    await moveFiles(ctx, { collection: 'hb', place: 'field-ssd' }, 'archive')

    expect(calls[0].body).toMatchObject({
      collection: 'hb',
      place: 'field-ssd',
      volume: 'archive',
    })
    // Tagged, so whatever it does first (downloading) shows as its progress.
    expect(calls[0].headers['x-civex-progress']).toBeTruthy()
    expect(toast.success).toHaveBeenCalledWith('Moved 3 files onto archive.')
  })

  it('says files came straight from the server when nothing else had to move', async () => {
    const calls = fakeServer({
      '/api/file-access/gather': {
        transfer_id: null,
        volume: 'default',
        files: 0,
        bytes: 0,
        downloaded: 2,
      },
    })
    const { ctx, toast } = context()

    await moveFiles(ctx, { within: 'r1' }, 'default')

    expect(calls.map((c) => c.path)).toEqual(['/api/file-access/gather'])
    expect(toast.success).toHaveBeenCalledWith(
      'Downloaded 2 files from the server onto default.',
    )
    expect(toast.error).not.toHaveBeenCalled()
  })

  it('downloads only what is on the server, with its progress followed', async () => {
    const calls = fakeServer({
      '/api/file-access/download': {
        fetched: 4,
        listed: 9,
        absent: 1,
        absent_where: [
          {
            reason: "It is still only on 'backup'.",
            fix: 'It arrives here once that computer syncs.',
            files: 1,
          },
        ],
      },
    })
    const { ctx, toast } = context()

    await downloadFiles(ctx, { within: 'r1', shas: ['a', 'b'] })

    expect(calls[0].body).toMatchObject({
      within: 'r1',
      shas: ['a', 'b'],
      place: 'server',
    })
    expect(calls[0].headers['x-civex-progress']).toBeTruthy()
    expect(toast.success).toHaveBeenCalledWith(
      "Downloaded 4 files. Some records share a file, so 9 listed files are on this computer now. 1 file not downloaded: It is still only on 'backup'. It arrives here once that computer syncs.",
    )
  })
})
