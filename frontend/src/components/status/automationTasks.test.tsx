import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { SHOW_AFTER_MS } from '../../hooks/tasks/useAutomationTasks'
import { TaskStatusBar } from './TaskStatusBar'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

interface State {
  paused: boolean
  pending: number
  running: number
  cancelled: number
  batch: Record<string, unknown> | null
}
let state: State
let calls: { method: string; path: string; search: string }[]
// What the server would count for the runs queued since a batch began.
let outcome: { total: number; failed: number }

const T0 = '2026-10-04T10:00:00Z'

/** What the server reports for a stretch of work: runs still going, and how the
 * finished ones came out. The total is the server's, not the client's guess. */
function work(
  pending: number,
  running: number,
  done: { completed?: number; failed?: number; cancelled?: number } = {},
): State {
  const { completed = 0, failed = 0, cancelled = 0 } = done
  const active = pending + running
  return {
    paused: false,
    pending,
    running,
    cancelled: 0,
    batch:
      active === 0
        ? null
        : {
            total: active + completed + failed + cancelled,
            active,
            completed,
            failed,
            cancelled,
            started_at: T0,
          },
  }
}

beforeEach(() => {
  calls = []
  outcome = { total: 0, failed: 0 }
  state = work(0, 0)
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      const method = init?.method ?? 'GET'
      calls.push({ method, path: url.pathname, search: url.search })
      if (url.pathname === '/api/automation/stop') {
        state = { ...work(0, 0), paused: true, cancelled: 3 }
        return json(state)
      }
      if (url.pathname === '/api/automation/resume') {
        state = { ...state, paused: false }
        return json(state)
      }
      if (url.pathname === '/api/automation') return json(state)
      if (url.pathname === '/api/jobs/count')
        return json({
          total: url.search.includes('failed') ? outcome.failed : outcome.total,
        })
      if (url.pathname === '/api/store/transfers') return json([])
      return json({})
    }),
  )
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

function renderIt() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <TaskStatusBar />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('the status bar, for workflow runs', () => {
  it('is nothing when workflows are idle', async () => {
    const { container } = renderIt()
    await waitFor(() => expect(calls.length).toBeGreaterThan(0))
    await new Promise((r) => setTimeout(r, 20))
    expect(container).toBeEmptyDOMElement()
  })

  it('says automation is paused, so a pause is not forgotten, and can resume it', async () => {
    state = { ...work(0, 0), paused: true }
    const user = userEvent.setup()
    renderIt()

    expect(await screen.findByText(/Automation is paused/)).toBeInTheDocument()
    expect(screen.getByText(/manual runs are refused/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Resume automation' }))

    await waitFor(() =>
      expect(
        calls.some(
          (c) => c.method === 'POST' && c.path === '/api/automation/resume',
        ),
      ).toBe(true),
    )
  })

  it('does not flash for an ordinary run that is over in a moment', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    state = work(0, 1)
    renderIt()
    await waitFor(() => expect(calls.length).toBeGreaterThan(0))

    await act(async () => {
      await vi.advanceTimersByTimeAsync(SHOW_AFTER_MS - 1000)
    })

    expect(screen.queryByText(/Workflows are running/)).toBeNull()
  })

  it('offers to stop workflows that have been busy for a while', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    state = work(24, 1)
    renderIt()
    await waitFor(() => expect(calls.length).toBeGreaterThan(0))

    await act(async () => {
      await vi.advanceTimersByTimeAsync(SHOW_AFTER_MS + 500)
    })

    expect(await screen.findByText('Workflows are running')).toBeInTheDocument()
  })

  it('stops everything after one confirmation, then shows the pause', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    state = work(5, 1)
    renderIt()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SHOW_AFTER_MS + 500)
    })
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })

    await user.click(
      await screen.findByRole('button', { name: /Stop automation/ }),
    )
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent(/Cancels waiting runs/)
    expect(calls.some((c) => c.path === '/api/automation/stop')).toBe(false) // not yet
    await user.click(
      within(dialog).getByRole('button', { name: 'Stop automation' }),
    )

    await waitFor(() =>
      expect(
        calls.some(
          (c) => c.method === 'POST' && c.path === '/api/automation/stop',
        ),
      ).toBe(true),
    )
    expect(await screen.findByText(/Automation is paused/)).toBeInTheDocument()
  })

  it('shows how far through a batch of runs it is, from the most there were at once', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    state = work(3, 1) // four queued at once
    renderIt()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SHOW_AFTER_MS + 500)
    })

    const bar = await screen.findByRole('progressbar', {
      name: 'Workflow runs finished',
    })
    expect(bar).toHaveAttribute('aria-valuenow', '0')

    // Two finish (one failed); the next poll sees two left of the same four.
    state = work(1, 1, { completed: 1, failed: 1 })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3500)
    })

    await waitFor(() =>
      expect(
        screen.getByRole('progressbar', { name: 'Workflow runs finished' }),
      ).toHaveAttribute('aria-valuenow', '50'),
    )
    expect(screen.getByText(/2 of 4 done/)).toBeInTheDocument()
    expect(screen.getByText(/1 succeeded/)).toBeInTheDocument()
    expect(screen.getByText(/1 succeeded · 1 failed/)).toBeInTheDocument()
    expect(screen.getByText(/1 waiting/)).toBeInTheDocument()
    expect(screen.queryByText(/running,/)).toBeNull()
  })

  it('draws no bar for a single run: there is nothing to measure it against', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    state = work(0, 1)
    renderIt()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SHOW_AFTER_MS + 500)
    })

    expect(await screen.findByText('Workflows are running')).toBeInTheDocument()
    // Nothing is queued behind it, and one at a time means "1 running" says
    // nothing: no counts at all.
    expect(screen.queryByText(/running,/)).toBeNull()
    expect(screen.queryByText(/waiting/)).toBeNull()
    expect(screen.queryByText(/\b0\b/)).toBeNull()
    expect(screen.queryByRole('progressbar')).toBeNull()
  })

  it('starts the batch afresh once everything has finished', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    state = work(4, 1)
    renderIt()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SHOW_AFTER_MS + 500)
    })
    await screen.findByRole('progressbar', { name: 'Workflow runs finished' })

    state = work(0, 0) // all done (and none failed)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3500)
    })
    await waitFor(() => expect(screen.queryByRole('status')).toBeNull())

    state = work(1, 1) // a new, smaller batch
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000)
    })

    // Measured against its own two, not the earlier five.
    expect(
      await screen.findByRole('progressbar', {
        name: 'Workflow runs finished',
      }),
    ).toHaveAttribute('aria-valuenow', '0')
    expect(screen.getByText(/0 of 2 done/)).toBeInTheDocument()
  })

  it('says only how many are waiting when that is all there is to say', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    state = work(3, 0) // between two runs
    renderIt()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SHOW_AFTER_MS + 500)
    })

    expect(await screen.findByText(/3 waiting/)).toBeInTheDocument()
    expect(screen.queryByText(/0 running/)).toBeNull()
  })

  it('shows a bulk start at once, with its true size, not a few seconds later saying what is left', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    state = work(49, 1) // fifty queued in one go
    renderIt()

    // No wait for SHOW_AFTER_MS: a batch is worth showing immediately.
    const bar = await screen.findByRole('progressbar', {
      name: 'Workflow runs finished',
    })
    expect(bar).toHaveAttribute('aria-valuenow', '0')
    expect(screen.getByText(/0 of 50 done/)).toBeInTheDocument()
  })

  it('still moves when every run fails, and says how many have', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    state = work(29, 1, { failed: 20 }) // twenty of fifty done, all errors
    renderIt()

    const bar = await screen.findByRole('progressbar', {
      name: 'Workflow runs finished',
    })
    expect(bar).toHaveAttribute('aria-valuenow', '40') // 20 of 50
    expect(screen.getByText(/20 of 50 done · 20 failed/)).toBeInTheDocument()
    expect(screen.queryByText(/succeeded/)).toBeNull() // none to count
  })

  it('links, as soon as there are failures, to just the failed runs of this batch', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    state = work(10, 1, { completed: 3, failed: 2 })
    renderIt()

    const link = await screen.findByRole('link', { name: 'See 2 failed' })
    const filter = JSON.parse(
      new URL(link.getAttribute('href')!, 'http://x').searchParams.get(
        'filter',
      )!,
    )
    expect(filter).toEqual({
      and: [
        { field: 'status', op: 'eq', value: 'failed' },
        { field: 'created_at', op: 'gte', value: T0 },
      ],
    })
  })

  it('keeps a notice of the failures after the batch ends, until dismissed', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    state = work(4, 1, { completed: 5, failed: 2 })
    renderIt()
    await screen.findByRole('progressbar', { name: 'Workflow runs finished' })

    outcome = { total: 12, failed: 3 } // the server's final count: one more failed
    state = work(0, 0)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3500)
    })

    expect(
      await screen.findByText('3 of 12 workflow runs failed'),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: 'See the failures' }),
    ).toHaveAttribute('href', expect.stringContaining('/runs?filter='))
    // still there a while later: errors are not swept away with the progress bar
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000)
    })
    expect(screen.getByText('3 of 12 workflow runs failed')).toBeInTheDocument()

    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    await user.click(screen.getByRole('button', { name: 'Dismiss' }))
    expect(screen.queryByText(/workflow runs failed/)).toBeNull()
  })

  it('leaves no notice when a batch ends with nothing wrong', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    state = work(4, 1, { completed: 3 })
    renderIt()
    await screen.findByRole('progressbar', { name: 'Workflow runs finished' })

    outcome = { total: 8, failed: 0 }
    state = work(0, 0)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3500)
    })

    await waitFor(() => expect(screen.queryByRole('progressbar')).toBeNull())
    expect(screen.queryByText(/failed/)).toBeNull()
  })

  it('goes to the next batch without the old notice', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    state = work(2, 1, { failed: 1 })
    renderIt()
    await screen.findByRole('progressbar', { name: 'Workflow runs finished' })
    outcome = { total: 4, failed: 2 }
    state = work(0, 0)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3500)
    })
    await screen.findByText('2 of 4 workflow runs failed')

    state = work(5, 1)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000)
    })

    expect(await screen.findByText('Workflows are running')).toBeInTheDocument()
    expect(screen.queryByText(/workflow runs failed/)).toBeNull()
  })
})
