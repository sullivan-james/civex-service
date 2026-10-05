import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SyncConflict } from '../../api/remote'
import { ConflictCard } from './ConflictCard'

const base: SyncConflict = {
  id: 'c1',
  kind: 'conflict',
  entity_type: 'record',
  entity_id: 'r1',
  field: 'data.f1',
  yours: 'phone',
  theirs: 'laptop',
  base: 'x',
  theirs_actor: 'laptop',
  theirs_at: '2026-10-05T10:00:00Z',
  device_name: null,
  message: null,
  status: 'open',
  created_at: '2026-10-05T10:05:00Z',
  resolved_at: null,
  resolution: null,
  record_name: 'Dive 12',
  dataset_name: 'study',
  schema_name: 'encounter',
  field_label: 'Site',
  dtype: 'string',
  current: 'laptop',
  stale: false,
  record_deleted: false,
  takes: ['theirs', 'mine', 'value'],
  also_saved: [],
}

let calls: { path: string; body: unknown }[]

beforeEach(() => {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({
        path: String(url),
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      })
      return new Response(JSON.stringify({}), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function show(c: Partial<SyncConflict> = {}, props = {}) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <ConflictCard conflict={{ ...base, ...c }} {...props} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const resolved = () => calls.find((c) => c.path.endsWith('/resolve'))?.body

describe('ConflictCard', () => {
  it('names the record and field and shows before, kept and yours', () => {
    show()
    expect(screen.getByRole('link', { name: 'Dive 12' })).toHaveAttribute(
      'href',
      '/records/r1',
    )
    expect(screen.getByText('Before')).toBeInTheDocument()
    expect(screen.getByText(/Kept/)).toHaveTextContent('laptop')
    expect(screen.getByText('x')).toBeInTheDocument()
    expect(screen.getByText('phone')).toBeInTheDocument()
  })

  it('keeps theirs', async () => {
    show()
    await userEvent.click(screen.getByRole('button', { name: 'Keep theirs' }))
    await waitFor(() =>
      expect(resolved()).toEqual({ take: 'theirs', force: undefined }),
    )
  })

  it('puts mine back without forcing when nothing has moved', async () => {
    show()
    await userEvent.click(screen.getByRole('button', { name: 'Use mine' }))
    await waitFor(() => expect(resolved()).toMatchObject({ take: 'mine' }))
    expect(resolved()).not.toMatchObject({ force: true })
  })

  it('warns when the value has changed again and offers to overwrite it', async () => {
    show({ stale: true, current: 'newer' })
    expect(screen.getByRole('status')).toHaveTextContent('changed again')
    expect(screen.getByRole('status')).toHaveTextContent('newer')
    await userEvent.click(
      screen.getByRole('button', { name: 'Use mine anyway' }),
    )
    await waitFor(() =>
      expect(resolved()).toMatchObject({ take: 'mine', force: true }),
    )
  })

  it('lets a person type another value', async () => {
    show()
    await userEvent.click(screen.getByRole('button', { name: 'Edit…' }))
    const input = screen.getByLabelText('New value for Site')
    await userEvent.clear(input)
    await userEvent.type(input, 'both')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(resolved()).toMatchObject({ take: 'value', value: 'both' }),
    )
  })

  it('does not offer to retype a field it cannot retype', () => {
    show({ dtype: 'geo' })
    expect(screen.queryByRole('button', { name: 'Edit…' })).toBeNull()
  })

  it('offers only what the server says can be done', () => {
    show({
      kind: 'edit_vs_delete',
      takes: ['theirs', 'delete'],
      message: 'Deleted there',
    })
    expect(screen.getByRole('button', { name: 'Keep it' })).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Delete it' }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Use mine' })).toBeNull()
  })

  it('says why a change was refused and offers to send it again', async () => {
    show({
      kind: 'rejected',
      field: null,
      takes: ['theirs', 'retry'],
      message: 'A Site with the same name already exists',
    })
    expect(screen.getByText(/already exists/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Send again' }))
    await waitFor(() => expect(resolved()).toMatchObject({ take: 'retry' }))
  })

  it('names the other values of the same edit that did go in', async () => {
    show({ also_saved: [{ field_label: 'Depth', value: 7 }] })
    await userEvent.click(screen.getByRole('button', { name: /1 other value/ }))
    expect(screen.getByText('Depth:')).toBeInTheDocument()
  })

  it('takes the first two choices from the keyboard when asked to', async () => {
    show({}, { shortcuts: true })
    await userEvent.keyboard('2')
    await waitFor(() => expect(resolved()).toMatchObject({ take: 'mine' }))
  })

  it('says what was refused when settling fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(JSON.stringify({ detail: 'Site must be unique' }), {
            status: 422,
            headers: { 'Content-Type': 'application/json' },
          }),
      ),
    )
    show()
    await userEvent.click(screen.getByRole('button', { name: 'Use mine' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Site must be unique',
    )
  })
})
