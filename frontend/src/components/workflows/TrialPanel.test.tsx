import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import type { TrialOnRecord, TrialResult } from '../../api/workflows'
import { TrialPanel } from './TrialPanel'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const ok = (after: string): TrialResult => ({
  ok: true,
  steps: [],
  changes: [
    {
      record_id: 'r1',
      schema_name: 'rec',
      name: 'Dive 7',
      action: 'updated',
      fields: [
        {
          field: 'title',
          label: 'Title',
          dtype: 'string',
          before: 'old',
          after,
        },
      ],
    },
  ],
  would_start: {},
  error: null,
  log: null,
})

let answer: (body: { content: string }) => {
  body: unknown
  status?: number
}
let sent: { content: string; record_ids: string[] }[]

beforeEach(() => {
  sent = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      if (url.pathname.endsWith('/workflows/try-many')) {
        const body = JSON.parse(String(init?.body))
        sent.push(body)
        const a = answer(body)
        return json(a.body, a.status ?? 200)
      }
      if (url.pathname.endsWith('/schemas'))
        return json([{ id: 's', name: 'rec', label: 'Recording', fields: [] }])
      return json([])
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

const trials = (...ts: TrialOnRecord[]) => ({ trials: ts, sampled: true })
const on = (record_id: string, result: TrialResult | null, problem = null) => ({
  record_id,
  name: record_id === 'r1' ? 'Dive 7' : 'Dive 8',
  result,
  problem,
})

function renderIt(props: Partial<Parameters<typeof TrialPanel>[0]> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const view = (p: Partial<Parameters<typeof TrialPanel>[0]>) => (
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <TrialPanel
          content="name: x"
          schema="rec"
          inputs={{}}
          plugins={[]}
          {...props}
          {...p}
        />
      </MemoryRouter>
    </QueryClientProvider>
  )
  const r = render(view({}))
  return {
    rerender: (p: Partial<Parameters<typeof TrialPanel>[0]>) =>
      r.rerender(view(p)),
  }
}

describe('TrialPanel (the live preview)', () => {
  it('runs by itself on the latest records and says what each would get', async () => {
    answer = () => ({
      body: trials(on('r1', ok('new')), on('r2', ok('other'))),
    })
    renderIt()
    expect(
      await screen.findByText(/Would change every one\./),
    ).toBeInTheDocument()
    expect(sent[0]).toEqual({ content: 'name: x', record_ids: [], sample: 5 })
    expect(screen.getByText('Dive 7')).toBeInTheDocument()
    expect(screen.getByText('new')).toBeInTheDocument()
    expect(
      screen.getByText(/On the 2 Recording records changed last/),
    ).toBeInTheDocument()
  })

  it('runs again when the workflow changes and marks what changed', async () => {
    answer = ({ content }) => ({
      body: trials(
        on('r1', ok(content === 'name: x' ? 'new' : 'newer')),
        on('r2', ok('same')),
      ),
    })
    const { rerender } = renderIt()
    await screen.findByText('new')
    rerender({ content: 'name: y' })
    expect(
      await screen.findByText('newer', {}, { timeout: 3000 }),
    ).toBeInTheDocument()
    const badges = screen.getAllByText('Changed')
    expect(badges).toHaveLength(1)
    expect(sent.map((b) => b.content)).toEqual(['name: x', 'name: y'])
  })

  it('says where it fails', async () => {
    answer = () => ({
      body: trials(
        on('r1', {
          ok: false,
          steps: [
            {
              step_id: 'read',
              plugin: 'p',
              status: 'failed',
              inputs: {},
              outputs: null,
              duration_seconds: 0,
              error: 'boom',
              depends_on: [],
            },
          ],
          changes: [],
          would_start: {},
          error: {
            kind: 'not_found',
            message: "Field 'x' not found",
            retryable: false,
            step: 'read',
          },
          log: null,
        }),
      ),
    })
    renderIt()
    expect(
      await screen.findByText(/Step 1 fails: Field 'x' not found/),
    ).toBeInTheDocument()
    expect(screen.getByText(/Fails on 1 of 1/)).toBeInTheDocument()
  })

  it('lists what the server says is wrong with the workflow', async () => {
    answer = () => ({
      status: 422,
      body: { detail: [{ step: 'read', message: "Unknown plugin 'nope'" }] },
    })
    const onInvalid = vi.fn()
    renderIt({ onInvalid })
    await waitFor(() =>
      expect(screen.getByText(/Unknown plugin 'nope'/)).toBeInTheDocument(),
    )
    expect(onInvalid).toHaveBeenCalledTimes(1)
  })

  it('waits while there is something left to choose', async () => {
    answer = () => ({ body: trials() })
    renderIt({ ready: false, waiting: 'Choose 2 more things.' })
    expect(screen.getByText('Choose 2 more things.')).toBeInTheDocument()
    await new Promise((r) => setTimeout(r, 800))
    expect(sent).toEqual([])
  })
})
