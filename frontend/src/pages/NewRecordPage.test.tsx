import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router'
import { ToastProvider } from '../components/ui'
import NewRecordPage from './NewRecordPage'

const field = (name: string, type: string, required = false) => ({
  id: `f-${name}`,
  name,
  label: null,
  type,
  required,
  restrictions: type === 'integer' ? { min: 0, max: 10 } : {},
  default: null,
  position: 0,
})
const SCHEMAS = [
  {
    id: 's1',
    name: 'encounter',
    label: null,
    description: null,
    parent_id: null,
    display_template: null,
    deleted_at: null,
    fields: [field('site', 'string', true), field('depth', 'integer')],
  },
]
const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })

let posted: unknown
beforeEach(() => {
  posted = null
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      if (init?.method === 'POST' && url.pathname.endsWith('/records')) {
        posted = JSON.parse(String(init.body))
        return json({ id: 'new1', natural_name: 'N', data: {} })
      }
      if (url.pathname === '/api/schemas') return json(SCHEMAS)
      if (url.pathname === '/api/collections/hb')
        return json({ id: 'c', name: 'hb', description: null, record_count: 0 })
      return json({})
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

describe('NewRecordPage', () => {
  it('shows blank rows with their rules, and adds what was filled in', async () => {
    const user = userEvent.setup()
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ToastProvider>
          <MemoryRouter
            initialEntries={['/collections/hb/new?schema=encounter']}
          >
            <Routes>
              <Route path="/collections/:id/new" element={<NewRecordPage />} />
              <Route path="/records/:id" element={<p>created</p>} />
            </Routes>
          </MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>,
    )
    expect(await screen.findByText('0 – 10')).toBeInTheDocument()

    await user.click(screen.getAllByTitle('Click to edit')[0])
    await user.type(screen.getByRole('textbox'), 'Stellwagen{Enter}')
    await user.click(screen.getByRole('button', { name: 'Add encounter' }))

    await waitFor(() => expect(posted).not.toBeNull())
    expect(posted).toMatchObject({
      schema_name: 'encounter',
      data: { site: 'Stellwagen' },
    })
    expect(await screen.findByText('created')).toBeInTheDocument()
  })
})
