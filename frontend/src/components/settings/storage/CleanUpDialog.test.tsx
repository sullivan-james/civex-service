import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { CleanUpDialog } from './CleanUpDialog'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const MB = 1024 ** 2
const obj = (volume: string, size: number, i: number) => ({
  sha256: String(i).padStart(64, '0'),
  volume,
  size,
  mtime: 0,
})

const report = (over: Record<string, unknown> = {}) => ({
  dry_run: true,
  grace_days: 14,
  scanned: 50,
  referenced: 45,
  protected_by_grace: 2,
  deleted_count: 3,
  deleted_bytes: 30 * MB,
  deleted: [
    obj('archive', 10 * MB, 1),
    obj('archive', 10 * MB, 2),
    obj('usb', 10 * MB, 3),
  ],
  stale_scratch_removed: 0,
  volume: null,
  ...over,
})

let calls: { path: string; body: Record<string, unknown> }[]
let answer: (body: Record<string, unknown>) => Response

beforeEach(() => {
  calls = []
  answer = (body) =>
    body.apply
      ? json(report({ dry_run: false }))
      : json(report({ volume: body.volume ?? null }))
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      const body = init?.body ? JSON.parse(String(init.body)) : {}
      calls.push({ path: url.pathname, body })
      if (url.pathname === '/api/store/gc') return answer(body)
      return json({})
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function renderIt(volume?: string, onClose = () => {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <CleanUpDialog volume={volume} onClose={onClose} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const gcCalls = () => calls.filter((c) => c.path === '/api/store/gc')

describe('CleanUpDialog', () => {
  it('looks as soon as it opens, changing nothing, and says what it found', async () => {
    renderIt()

    expect(
      await screen.findByText(/3 files \(30\.0 MB\)/, { selector: 'strong' }),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/not used by any record or workflow run/),
    ).toBeVisible()
    expect(gcCalls()).toEqual([
      { path: '/api/store/gc', body: { apply: false, grace_days: 14 } },
    ])
  })

  it('says which volumes the files are on when it covers every volume', async () => {
    renderIt()

    expect(await screen.findByText('archive: 2 files (20.0 MB)')).toBeVisible()
    expect(screen.getByText('usb: 1 file (10.0 MB)')).toBeVisible()
  })

  it('is limited to one volume when opened from that volume', async () => {
    answer = (body) =>
      json(
        report({
          volume: body.volume,
          deleted_count: 2,
          deleted_bytes: 20 * MB,
          deleted: [obj('archive', 10 * MB, 1), obj('archive', 10 * MB, 2)],
        }),
      )
    renderIt('archive')

    expect(
      await screen.findByRole('heading', {
        name: 'Clean up unused files on archive',
      }),
    ).toBeInTheDocument()
    expect(
      await screen.findByText(/2 files \(20\.0 MB\)/, { selector: 'strong' }),
    ).toBeVisible()
    expect(screen.getByText(/on 'archive'/)).toBeVisible()
    expect(gcCalls()[0].body).toMatchObject({ volume: 'archive', apply: false })
    // One volume: no breakdown by volume is needed.
    expect(screen.queryByText(/archive: 2 files/)).toBeNull()
  })

  it('deletes exactly what it showed, on the same volume, then says what was freed', async () => {
    answer = (body) =>
      body.apply
        ? json(
            report({
              dry_run: false,
              deleted_bytes: 20 * MB,
              deleted_count: 2,
            }),
          )
        : json(report({ deleted_count: 2, deleted_bytes: 20 * MB }))
    const user = userEvent.setup()
    renderIt('archive')

    await user.click(
      await screen.findByRole('button', { name: 'Delete 2 files (20.0 MB)' }),
    )

    expect(await screen.findByRole('status')).toHaveTextContent(
      'Freed 20.0 MB: deleted 2 files.',
    )
    expect(gcCalls()[1].body).toEqual({
      apply: true,
      grace_days: 14,
      volume: 'archive',
    })
    // Finished: nothing more to delete, and the way out is "Done".
    expect(screen.queryByRole('button', { name: /^Delete/ })).toBeNull()
    expect(screen.getByRole('button', { name: 'Done' })).toBeInTheDocument()
  })

  it('says plainly when there is nothing to clean up, with no delete button', async () => {
    answer = () =>
      json(report({ deleted_count: 0, deleted_bytes: 0, deleted: [] }))
    renderIt()

    expect(
      await screen.findByText(/Nothing to clean up on any volume/),
    ).toBeVisible()
    expect(
      screen.getByText(/added in the last 14 days \(2 files\)/),
    ).toBeVisible()
    expect(screen.queryByRole('button', { name: /^Delete/ })).toBeNull()
  })

  it('shows why it could not run, such as a move holding the store', async () => {
    answer = () =>
      json(
        { detail: 'A storage transfer is running. Garbage collection waits.' },
        409,
      )
    renderIt()

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'A storage transfer is running',
    )
    expect(screen.queryByRole('button', { name: /^Delete/ })).toBeNull()
  })

  it('can keep recent files for longer and check again', async () => {
    const user = userEvent.setup()
    renderIt()
    await screen.findByRole('button', { name: /^Delete 3 files/ })

    await user.click(screen.getByRole('button', { name: /Options/ }))
    const days = screen.getByLabelText(/Keep files added in the last/)
    await user.clear(days)
    await user.type(days, '30')
    await user.click(screen.getByRole('button', { name: 'Check again' }))

    await waitFor(() =>
      expect(gcCalls().at(-1)?.body).toEqual({ apply: false, grace_days: 30 }),
    )
  })

  it('can be closed without deleting anything', async () => {
    const onClose = vi.fn()
    const user = userEvent.setup()
    renderIt(undefined, onClose)
    await screen.findByRole('button', { name: /^Delete 3 files/ })

    // The header's X and the footer button both close it.
    await user.click(screen.getAllByRole('button', { name: 'Close' }).at(-1)!)

    expect(onClose).toHaveBeenCalled()
    expect(gcCalls().every((c) => c.body.apply === false)).toBe(true)
  })
})
