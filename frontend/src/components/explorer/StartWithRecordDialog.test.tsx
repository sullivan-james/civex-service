import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { ToastProvider } from '../ui'
import { StartWithRecordDialog } from './StartWithRecordDialog'
import type { Collection } from '../../api/collections'

const COLLECTION: Collection = {
  id: 'c1',
  name: 'survey-2024',
  description: null,
  timezone: null,
  record_count: 0,
  deleted_at: null,
  scope: 'local',
  schemas: [],
}

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })

let calls: { method: string; path: string; body?: unknown }[]
beforeEach(() => {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      const method = init?.method ?? 'GET'
      calls.push({
        method,
        path: url.pathname,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      })
      if (method === 'POST' && url.pathname === '/api/schemas')
        return json({ id: 's1', name: 'sample', label: 'Sample', fields: [] })
      if (method === 'PATCH' && url.pathname === '/api/collections/survey-2024')
        return json({ ...COLLECTION, schemas: ['sample'] })
      return json({})
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function Where() {
  const { pathname, search } = useLocation()
  return <output data-testid="where">{pathname + search}</output>
}

describe('StartWithRecordDialog', () => {
  it('makes the record type, lists it on the collection and opens a blank record of it', async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ToastProvider>
          <MemoryRouter initialEntries={['/collections/c1']}>
            <Routes>
              <Route
                path="*"
                element={
                  <>
                    <StartWithRecordDialog
                      collection={COLLECTION}
                      onClose={onClose}
                    />
                    <Where />
                  </>
                }
              />
            </Routes>
          </MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>,
    )
    const go = screen.getByRole('button', { name: /Add the first record/ })
    expect(go).toBeDisabled()
    await user.type(screen.getByLabelText(/Record type label/), 'Sample')
    expect(go).toBeEnabled()
    await user.click(go)

    await waitFor(() =>
      expect(screen.getByTestId('where').textContent).toBe(
        '/collections/c1/new?schema=sample',
      ),
    )
    const posted = calls.find(
      (c) => c.method === 'POST' && c.path === '/api/schemas',
    )
    expect(posted?.body).toEqual({ name: 'sample', label: 'Sample' })
    const patched = calls.find(
      (c) => c.method === 'PATCH' && c.path === '/api/collections/survey-2024',
    )
    expect(patched?.body).toEqual({ schemas: ['sample'] })
    expect(onClose).toHaveBeenCalled()
  })
})
