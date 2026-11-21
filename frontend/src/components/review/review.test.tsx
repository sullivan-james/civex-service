import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import type { ReactNode } from 'react'
import type { Note } from '../../api/review'
import { ToastProvider } from '../ui/ToastProvider'
import { NotesPanel } from './NotesPanel'
import { ReviewStatusMenu } from './ReviewStatusMenu'
import { ReviewSelectionMenu } from './ReviewSelectionMenu'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const note = (over: Partial<Note>): Note => ({
  id: 'n1',
  record_id: 'r1',
  body: 'depth looks off',
  author: 'ana',
  created_at: '2026-11-20T10:00:00Z',
  edited_at: null,
  resolved_at: null,
  resolved_by: null,
  deleted_at: null,
  ...over,
})

let notes: Note[]
let calls: { method: string; path: string; body?: unknown }[]
let writer: boolean

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter>{ui}</MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  writer = true
  notes = [
    note({}),
    note({ id: 'n2', author: 'ben', body: 'calibrated on the 3rd' }),
  ]
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
      if (url.pathname === '/api/me')
        return json({
          account: { name: 'ana', kind: 'local', manage_url: null },
          permissions: {
            actions: writer
              ? { read: ['project'], write_records: ['project'] }
              : { read: ['project'] },
            all: { write_records: 'add and change records' },
          },
        })
      if (url.pathname === '/api/records/r1/notes' && method === 'GET')
        return json(notes)
      if (url.pathname === '/api/records/review')
        return json({ status: 'checked', records: 2, changed: 2, unchanged: 0 })
      return json(note({}))
    }),
  )
})

afterEach(() => vi.unstubAllGlobals())

describe('NotesPanel', () => {
  it('lists the notes with who wrote them, and lets only the author edit', async () => {
    wrap(<NotesPanel recordId="r1" collectionId="c1" />)
    expect(await screen.findByText('depth looks off')).toBeInTheDocument()
    expect(screen.getByText('calibrated on the 3rd')).toBeInTheDocument()
    expect(screen.getByText('ben')).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getAllByRole('button', { name: 'Edit' })).toHaveLength(1),
    )
    expect(screen.getAllByRole('button', { name: 'Resolve' })).toHaveLength(2)
  })

  it('adds a note and resolves one', async () => {
    const user = userEvent.setup()
    wrap(<NotesPanel recordId="r1" collectionId="c1" />)
    await screen.findByText('depth looks off')
    await user.type(
      screen.getByRole('textbox', { name: 'New note' }),
      're-check the calibration',
    )
    await user.click(screen.getByRole('button', { name: 'Add note' }))
    await waitFor(() =>
      expect(calls).toContainEqual({
        method: 'POST',
        path: '/api/records/r1/notes',
        body: { body: 're-check the calibration' },
      }),
    )
    await user.click(screen.getAllByRole('button', { name: 'Resolve' })[0])
    await waitFor(() =>
      expect(calls).toContainEqual({
        method: 'POST',
        path: '/api/notes/n1/resolve',
        body: { resolved: true },
      }),
    )
  })

  it('switches writing off, saying why, for someone who may only read', async () => {
    writer = false
    wrap(<NotesPanel recordId="r1" collectionId="c1" />)
    await screen.findByText('depth looks off')
    await waitFor(() =>
      expect(screen.getByRole('textbox', { name: 'New note' })).toBeDisabled(),
    )
  })
})

describe('ReviewStatusMenu', () => {
  it('shows the status and marks the record from its menu', async () => {
    const user = userEvent.setup()
    wrap(
      <ReviewStatusMenu
        recordId="r1"
        collectionId="c1"
        review={{
          status: 'needs_check',
          by: 'ana',
          at: '2026-11-20T10:00:00Z',
        }}
      />,
    )
    await user.click(
      screen.getByRole('button', { name: 'Review: Needs a check' }),
    )
    await user.click(screen.getByText('Mark as checked'))
    await waitFor(() =>
      expect(calls).toContainEqual({
        method: 'POST',
        path: '/api/records/review',
        body: { ids: ['r1'], status: 'checked' },
      }),
    )
  })
})

describe('ReviewSelectionMenu', () => {
  it('marks everything a list matches with one request', async () => {
    const user = userEvent.setup()
    const onDone = vi.fn()
    wrap(
      <ReviewSelectionMenu
        selection={{
          query: { schema: 'sample', search: 'x' },
          collection: 'survey',
        }}
        count={40}
        collectionId="c1"
        onDone={onDone}
      />,
    )
    await user.click(screen.getByRole('button', { name: /Review/ }))
    await user.click(screen.getByText('Mark as checked'))
    await waitFor(() => expect(onDone).toHaveBeenCalled())
    const sent = calls.find((c) => c.path === '/api/records/review')
    expect(sent?.body).toMatchObject({
      collection: 'survey',
      schema_name: 'sample',
      search: 'x',
      status: 'checked',
    })
  })
})
