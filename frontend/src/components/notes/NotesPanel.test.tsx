import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import type { ReactNode } from 'react'
import type { Note } from '../../api/notes'
import { ToastProvider } from '../ui/ToastProvider'
import { NotesPanel } from './NotesPanel'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const note = (over: Partial<Note>): Note => ({
  id: 'n1',
  record_id: 'r1',
  thread_id: null,
  body: 'depth looks off',
  author: 'ana',
  created_at: '2026-11-20T10:00:00Z',
  edited_at: null,
  resolved_at: null,
  resolved_by: null,
  deleted_at: null,
  replies: [],
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
    note({
      replies: [
        note({
          id: 'n3',
          thread_id: 'n1',
          author: 'ben',
          body: 'it was the sensor',
        }),
      ],
    }),
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
      return json(note({}))
    }),
  )
})

afterEach(() => vi.unstubAllGlobals())

describe('NotesPanel', () => {
  it('lists threads with their replies, and lets only the author edit', async () => {
    wrap(<NotesPanel recordId="r1" collectionId="c1" />)
    expect(await screen.findByText('depth looks off')).toBeInTheDocument()
    expect(screen.getByText('it was the sensor')).toBeInTheDocument()
    expect(screen.getByText('calibrated on the 3rd')).toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getAllByRole('button', { name: 'Edit' })).toHaveLength(1),
    )
    // Resolve is on each thread, not on a reply; each thread has a Reply box.
    expect(screen.getAllByRole('button', { name: 'Resolve' })).toHaveLength(2)
    expect(screen.getAllByRole('textbox', { name: 'Reply' })).toHaveLength(2)
    expect(
      screen.getByRole('link', { name: 'All open notes' }),
    ).toHaveAttribute('href', expect.stringContaining('tab=records'))
  })

  it('replies in a thread', async () => {
    const user = userEvent.setup()
    wrap(<NotesPanel recordId="r1" collectionId="c1" />)
    await screen.findByText('depth looks off')
    await user.type(
      screen.getAllByRole('textbox', { name: 'Reply' })[0],
      'thanks',
    )
    await user.click(screen.getAllByRole('button', { name: 'Reply' })[0])
    await waitFor(() =>
      expect(calls).toContainEqual({
        method: 'POST',
        path: '/api/notes/n1/replies',
        body: { body: 'thanks' },
      }),
    )
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
    expect(screen.queryByRole('textbox', { name: 'Reply' })).toBeNull()
  })
})
