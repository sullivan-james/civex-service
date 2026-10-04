import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { ToastProvider } from '../ui/ToastProvider'
import RetentionSection from './RetentionSection'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

let settings: Record<string, unknown>
let report: Record<string, unknown>
let purged: number
let calls: {
  method: string
  path: string
  body: Record<string, unknown> | undefined
}[]

const emptyReport = {
  dry_run: true,
  deleted_records: 0,
  deleted_collections: 0,
  deleted_schemas: 0,
  skipped: [],
  audit_entries: 0,
  audit_batches: 0,
  audit_kept_restorable: 0,
  audit_kept_unsynced: 0,
  runs: 0,
  run_steps: 0,
  anything: false,
}

beforeEach(() => {
  settings = {
    purge_after_days: 30,
    auto_purge_deleted: false,
    audit_days: null,
    run_days: null,
  }
  report = emptyReport
  purged = 0
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      calls.push({ method: init?.method ?? 'GET', path: url.pathname, body })
      if (url.pathname === '/api/settings/retention') {
        if (init?.method === 'PATCH') settings = { ...settings, ...body }
        return json(settings)
      }
      if (url.pathname === '/api/retention/purged-history')
        return json({ dry_run: body.dry_run, entries: purged })
      if (url.pathname === '/api/retention/run')
        return json({ ...report, dry_run: body.dry_run })
      return json({})
    }),
  )
})

afterEach(() => vi.unstubAllGlobals())

function renderSection() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter>
          <RetentionSection />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

describe('RetentionSection', () => {
  it('starts as keep-forever for history and runs, so there is nothing to apply', async () => {
    renderSection()
    expect(await screen.findByText('Change history')).toBeInTheDocument()
    expect(
      screen.getByRole('checkbox', { name: 'Keep history forever' }),
    ).toBeChecked()
    expect(
      screen.getByRole('checkbox', { name: 'Keep runs and logs forever' }),
    ).toBeChecked()
    expect(screen.getByRole('button', { name: /Clean up now/ })).toBeDisabled()
  })

  it('saves a period, and forever as null', async () => {
    renderSection()
    await userEvent.click(
      await screen.findByRole('checkbox', { name: 'Keep history forever' }),
    )
    const days = screen.getByLabelText('Keep history for (days), days')
    await userEvent.clear(days)
    await userEvent.type(days, '365')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => {
      const patch = calls.find((c) => c.method === 'PATCH')!
      expect(patch.body).toMatchObject({
        audit_days: 365,
        run_days: null,
        auto_purge_deleted: false,
        purge_after_days: 30,
      })
    })
  })

  it('refuses a nonsense period', async () => {
    renderSection()
    await userEvent.click(
      await screen.findByRole('checkbox', { name: 'Keep history forever' }),
    )
    const days = screen.getByLabelText('Keep history for (days), days')
    await userEvent.clear(days)
    await userEvent.type(days, '0')
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  })

  it('previews a clean-up by date before anything is removed', async () => {
    report = {
      ...emptyReport,
      audit_entries: 1200,
      audit_kept_restorable: 3,
      anything: true,
    }
    renderSection()
    const preview = await screen.findByRole('button', { name: 'Preview…' })
    expect(preview).toBeDisabled()
    await userEvent.type(
      screen.getByLabelText('Change history before'),
      '2026-01-01',
    )
    await userEvent.click(preview)

    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('Change history removed: 1,200 entries')
    expect(dialog).toHaveTextContent('3 older history entries kept')
    const run = calls.filter((c) => c.path === '/api/retention/run')
    expect(run).toHaveLength(1)
    expect(run[0].body).toMatchObject({ dry_run: true })
    expect(run[0].body!.audit_before).toMatch(/^2026-01-01T|^2025-12-31T/)
    expect(run[0].body!.deleted_before).toBeNull()
  })

  it('removes only after "delete" is typed', async () => {
    report = { ...emptyReport, runs: 40, run_steps: 90, anything: true }
    renderSection()
    await userEvent.type(
      await screen.findByLabelText('Workflow runs before'),
      '2026-01-01',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Preview…' }))
    const dialog = await screen.findByRole('dialog')
    const confirm = within(dialog).getByRole('button', {
      name: 'Delete for good',
    })
    expect(confirm).toBeDisabled()
    await userEvent.type(within(dialog).getByRole('textbox'), 'delete')
    expect(confirm).toBeEnabled()
    await userEvent.click(confirm)
    await waitFor(() => {
      const real = calls.filter(
        (c) => c.path === '/api/retention/run' && c.body?.dry_run === false,
      )
      expect(real).toHaveLength(1)
    })
  })

  it('says so when nothing is old enough', async () => {
    renderSection()
    await userEvent.type(
      await screen.findByLabelText('Change history before'),
      '2026-01-01',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Preview…' }))
    expect(
      await screen.findByText('Nothing is old enough to remove.'),
    ).toBeInTheDocument()
  })

  it('says nothing about leftover history when there is none', async () => {
    renderSection()
    await screen.findByText('Change history')
    expect(
      screen.queryByText(/History of permanently deleted records/),
    ).toBeNull()
  })

  it('offers to delete leftover history of purged records, after counting it', async () => {
    purged = 12
    renderSection()
    expect(
      await screen.findByText('History of permanently deleted records'),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/12 history entries still hold/),
    ).toBeInTheDocument()
    await userEvent.click(
      screen.getByRole('button', { name: /Delete that history/ }),
    )
    const dialog = await screen.findByRole('dialog')
    const confirm = within(dialog).getByRole('button', {
      name: 'Delete history',
    })
    expect(confirm).toBeDisabled()
    await userEvent.type(within(dialog).getByRole('textbox'), 'delete')
    await userEvent.click(confirm)
    await waitFor(() =>
      expect(
        calls.some(
          (c) =>
            c.path === '/api/retention/purged-history' &&
            c.body?.dry_run === false,
        ),
      ).toBe(true),
    )
  })
})
