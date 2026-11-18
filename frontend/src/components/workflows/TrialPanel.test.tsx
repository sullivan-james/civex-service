import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import type { TrialResult } from '../../api/workflows'
import { TrialPanel } from './TrialPanel'

const RID = '3f2b8c1e-0000-4000-8000-123456789abc'
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

let trialAnswer: { body: unknown; status: number }
let sent: unknown

beforeEach(() => {
  sent = undefined
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      if (url.pathname.endsWith('/workflows/try')) {
        sent = JSON.parse(String(init?.body))
        return json(trialAnswer.body, trialAnswer.status)
      }
      if (url.pathname.endsWith('/records'))
        return json([
          { id: RID, natural_name: 'Dive 7', schema_name: 'rec', data: {} },
        ])
      if (url.pathname.includes('/records/')) return json(null, 404)
      return json([])
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function renderIt(after = vi.fn(() => null)) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <TrialPanel
          content="name: x"
          schema="rec"
          inputs={{}}
          plugins={[]}
          after={after}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function pickAndTry() {
  const user = userEvent.setup()
  const search = screen.getByPlaceholderText('Search rec records')
  await user.click(search)
  const option = await screen.findByText('Dive 7')
  fireEvent.mouseDown(option)
  await user.click(screen.getByRole('button', { name: 'Try it' }))
}

describe('TrialPanel', () => {
  it('shows what would change, field by field, and that nothing was kept', async () => {
    const result: TrialResult = {
      ok: true,
      steps: [],
      changes: [
        {
          record_id: RID,
          schema_name: 'rec',
          name: 'Dive 7',
          action: 'updated',
          fields: [
            {
              field: 'title',
              label: 'Title',
              dtype: 'string',
              before: 'old',
              after: 'new',
            },
          ],
        },
      ],
      would_start: { 'Calculate stats': 2 },
      error: null,
      log: null,
    }
    trialAnswer = { body: result, status: 200 }
    const after = vi.fn(() => null)
    renderIt(after)
    await pickAndTry()

    expect(
      await screen.findByText(/It would change 1 record\./),
    ).toBeInTheDocument()
    expect(screen.getByText(/Nothing was kept/)).toBeInTheDocument()
    expect(screen.getByText('Would change')).toBeInTheDocument()
    expect(screen.getByText('old')).toBeInTheDocument()
    expect(screen.getByText('new')).toBeInTheDocument()
    expect(
      screen.getByText(/also start “Calculate stats” on 2 records/),
    ).toBeInTheDocument()
    expect(sent).toEqual({ content: 'name: x', record_id: RID })
    expect(after).toHaveBeenCalledWith(result)
  })

  it('says which step failed and what to do', async () => {
    trialAnswer = {
      status: 200,
      body: {
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
      },
    }
    renderIt()
    await pickAndTry()
    expect(
      await screen.findByText(/Step 1 failed: Field 'x' not found/),
    ).toBeInTheDocument()
  })

  it('lists what the server says is wrong with the workflow', async () => {
    trialAnswer = {
      status: 422,
      body: { detail: [{ step: 'read', message: "Unknown plugin 'nope'" }] },
    }
    renderIt()
    await pickAndTry()
    await waitFor(() =>
      expect(screen.getByText(/Unknown plugin 'nope'/)).toBeInTheDocument(),
    )
  })
})
