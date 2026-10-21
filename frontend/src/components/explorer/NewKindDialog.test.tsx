import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { ToastProvider } from '../ui'
import { NewKindDialog } from './NewKindDialog'
import type { Collection } from '../../api/collections'
import type { Schema } from '../../api/schemas'

const schema = (name: string, parent_id: string | null): Schema => ({
  id: `id-${name}`,
  name,
  label: null,
  description: null,
  parent_id,
  display_template: null,
  deleted_at: null,
  fields: [],
})
const SITE = schema('site', null)
const VISIT = schema('visit', SITE.id)
const COLLECTION: Collection = {
  id: 'c1',
  name: 'survey-2024',
  description: null,
  timezone: null,
  record_count: 0,
  deleted_at: null,
  scope: 'local',
  schemas: ['site'],
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
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      calls.push({ method, path: url.pathname, body })
      if (method === 'POST' && url.pathname === '/api/schemas')
        return json({ ...schema(body.name, null), label: body.label })
      if (method === 'PATCH' && url.pathname === '/api/collections/survey-2024')
        return json({ ...COLLECTION, schemas: body.schemas })
      return json({})
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function Where() {
  const { pathname, search } = useLocation()
  return <output data-testid="where">{pathname + search}</output>
}

function renderDialog(props: Partial<Parameters<typeof NewKindDialog>[0]>) {
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
                  <NewKindDialog
                    collection={COLLECTION}
                    schemas={[SITE, VISIT]}
                    onClose={onClose}
                    {...props}
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
  return onClose
}
const where = () => screen.getByTestId('where').textContent

describe('NewKindDialog', () => {
  it('makes a new kind, lists it on the collection and opens a blank one', async () => {
    const user = userEvent.setup()
    const onClose = renderDialog({})
    await user.type(screen.getByLabelText(/What are you adding/), 'Sample')
    await user.click(screen.getByRole('button', { name: 'New sample' }))
    await waitFor(() =>
      expect(where()).toBe('/collections/c1/new?schema=sample'),
    )
    expect(
      calls.find((c) => c.method === 'POST' && c.path === '/api/schemas')?.body,
    ).toEqual({ name: 'sample', label: 'Sample', parent: undefined })
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({
      schemas: ['site', 'sample'],
    })
    expect(onClose).toHaveBeenCalled()
  })

  it('pressed inside a record, the kind goes inside that kind and under that record', async () => {
    const user = userEvent.setup()
    renderDialog({ within: { id: 'r1', schema: SITE } })
    await user.type(
      screen.getByLabelText(/What are you adding/),
      'Survey point',
    )
    await user.click(screen.getByRole('button', { name: 'New survey point' }))
    await waitFor(() =>
      expect(where()).toBe('/collections/c1/new?schema=survey_point&parent=r1'),
    )
    expect(
      calls.find((c) => c.method === 'POST' && c.path === '/api/schemas')?.body,
    ).toEqual({ name: 'survey_point', label: 'Survey point', parent: 'site' })
  })

  it('reuses a kind that exists where it fits, and refuses one that does not', async () => {
    const user = userEvent.setup()
    renderDialog({ within: { id: 'r1', schema: SITE } })
    const box = screen.getByLabelText(/What are you adding/)
    await user.type(box, 'Visit')
    expect(screen.getByText('You already have visits.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'New visit' }))
    await waitFor(() =>
      expect(where()).toBe('/collections/c1/new?schema=visit&parent=r1'),
    )
    expect(calls.some((c) => c.method === 'POST')).toBe(false)
    // visit is now listed on the collection, since it was not before
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({
      schemas: ['site', 'visit'],
    })
  })

  it('will not make a top-level kind of one that goes inside another', async () => {
    const user = userEvent.setup()
    renderDialog({})
    await user.type(screen.getByLabelText(/What are you adding/), 'Visit')
    expect(screen.getByText(/goes somewhere else/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^New/ })).toBeDisabled()
  })
})
