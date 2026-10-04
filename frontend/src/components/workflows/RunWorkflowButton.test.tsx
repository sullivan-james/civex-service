import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import type { Workflow } from '../../api/workflows'
import { ToastProvider } from '../ui/ToastProvider'
import { RunWorkflowButton } from './RunWorkflowButton'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const RID = '3f2b8c1e-0000-4000-8000-123456789abc'

const wf = (name: string, over: Partial<Workflow> = {}): Workflow => ({
  name,
  description: null,
  steps: 1,
  filename: `${name}.yaml`,
  stem: name,
  record_schema: null,
  inputs: null,
  ...over,
})

let calls: { method: string; path: string; body: unknown }[]
let runStatus: number

beforeEach(() => {
  calls = []
  runStatus = 200
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      calls.push({
        method: init?.method ?? 'GET',
        path: url.pathname,
        body:
          init?.body instanceof FormData
            ? 'form'
            : init?.body
              ? JSON.parse(String(init.body))
              : undefined,
      })
      if (url.pathname.endsWith('/run'))
        return runStatus === 200
          ? json({ id: 'j1' })
          : json({ detail: 'The queue is full' }, runStatus)
      return json({})
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function renderIt(workflows: Workflow[], onStarted = () => {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter>
          <RunWorkflowButton
            workflows={workflows}
            recordId={RID}
            onStarted={onStarted}
          />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

const runs = () => calls.filter((c) => c.path.endsWith('/run'))

describe('RunWorkflowButton', () => {
  it('shows nothing when no workflow applies', () => {
    renderIt([])
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('is one visible button when there is one workflow, and runs it at once', async () => {
    const user = userEvent.setup()
    renderIt([wf('ingest')])

    await user.click(screen.getByRole('button', { name: 'Run ingest' }))

    await waitFor(() => expect(runs()).toHaveLength(1))
    expect(runs()[0]).toMatchObject({
      method: 'POST',
      path: '/api/workflows/ingest/run',
      body: { record_id: RID },
    })
    expect(await screen.findByText('Started ingest.')).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).toBeNull() // no popup to click through
  })

  it('offers a way to see the run that was just started', async () => {
    const onStarted = vi.fn()
    const user = userEvent.setup()
    renderIt([wf('ingest')], onStarted)

    await user.click(screen.getByRole('button', { name: 'Run ingest' }))
    await user.click(await screen.findByRole('button', { name: 'View run' }))

    expect(onStarted).toHaveBeenCalled()
  })

  it('lists several workflows under one button, on the page', async () => {
    const user = userEvent.setup()
    renderIt([wf('ingest'), wf('export')])

    await user.click(screen.getByRole('button', { name: /Run workflow/ }))
    await user.click(screen.getByRole('menuitem', { name: 'export' }))

    await waitFor(() => expect(runs()).toHaveLength(1))
    expect(runs()[0].path).toBe('/api/workflows/export/run')
  })

  it('says why when it could not be started', async () => {
    runStatus = 503
    const user = userEvent.setup()
    renderIt([wf('ingest')])

    await user.click(screen.getByRole('button', { name: 'Run ingest' }))

    expect(await screen.findByText(/Couldn't start ingest/)).toBeInTheDocument()
    expect(screen.getByText(/The queue is full/)).toBeInTheDocument()
  })

  it('asks for files only when the workflow needs them, and never shows the record ID', async () => {
    const user = userEvent.setup()
    renderIt([
      wf('load', {
        inputs: { scans: { type: 'files', label: 'Scans' } } as never,
      }),
    ])

    await user.click(screen.getByRole('button', { name: 'Run load' }))

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('Scans')).toBeInTheDocument()
    expect(within(dialog).getByText(/Drop files here or/)).toBeInTheDocument()
    expect(dialog).not.toHaveTextContent(RID)
    expect(dialog).not.toHaveTextContent(/Record ID/)
    expect(within(dialog).queryByRole('textbox')).toBeNull()
    expect(runs()).toHaveLength(0) // not run until the files are chosen and Run pressed

    await user.upload(
      within(dialog).getByLabelText('Scans: choose files'),
      new File(['x'], 'a.png'),
    )
    expect(within(dialog).getByText('a.png')).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Run' }))

    await waitFor(() => expect(runs()).toHaveLength(1))
    expect(runs()[0].body).toBe('form') // the files go with the run
    expect(await screen.findByText('Started load.')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })
})
