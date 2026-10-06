import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SyncConflict } from '../../api/remote'
import type { Field } from '../../api/schemas'
import { MergeView } from './MergeView'

const FIELDS: Field[] = [
  {
    id: 'f1',
    name: 'site',
    label: 'Site',
    type: 'string',
    required: false,
    restrictions: {},
    default: null,
    position: 0,
  },
  {
    id: 'f2',
    name: 'depth',
    label: 'Depth',
    type: 'float',
    required: false,
    restrictions: {},
    default: null,
    position: 1,
  },
]

function conflict(id: string, extra: Partial<SyncConflict> = {}): SyncConflict {
  return {
    id,
    kind: 'conflict',
    entity_type: 'record',
    entity_id: 'r1',
    field: 'data.f1',
    yours: 'north reef camp',
    theirs: 'south reef camp',
    base: 'reef camp',
    theirs_actor: 'laptop',
    theirs_at: '2026-10-05T10:00:00Z',
    device_name: null,
    message: null,
    status: 'open',
    created_at: `2026-10-05T10:0${id.slice(-1)}:00Z`,
    resolved_at: null,
    resolution: null,
    record_name: 'Dive',
    dataset_name: 'study',
    schema_name: 'encounter',
    field_label: 'Site',
    dtype: 'string',
    current: 'south reef camp',
    stale: false,
    record_deleted: false,
    takes: ['theirs', 'mine', 'value'],
    also_saved: [],
    attempted: null,
    changes: [],
    ...extra,
  }
}

let posts: { path: string; body: unknown }[]

beforeEach(() => {
  posts = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'POST')
        posts.push({ path: String(url), body: JSON.parse(String(init.body)) })
      return new Response(
        String(url).includes('/resolve-many')
          ? JSON.stringify({
              done: 2,
              settled_ids: [],
              not_offered: 0,
              failed: [],
            })
          : '[]',
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      )
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function show(conflicts: SyncConflict[], onSave = vi.fn()) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <MergeView
          recordId="r1"
          fields={FIELDS}
          data={{ site: 'south reef camp', depth: 9 }}
          conflicts={conflicts}
          onSave={onSave}
          onClose={vi.fn()}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return onSave
}

describe('MergeView', () => {
  it('puts the other side on the left, the result in the middle and yours on the right', () => {
    show([conflict('c1')])
    const row = screen.getByRole('group', { name: 'Site' })
    expect(within(row).getByText(/Before either of you/)).toBeInTheDocument()
    // Each side marks only the words the other lacks.
    expect(within(row).getByText('south').tagName).toBe('MARK')
    expect(within(row).getByText('north').tagName).toBe('MARK')
    expect(within(row).getAllByText(/reef camp/).length).toBeGreaterThan(1)
    expect(screen.getAllByText('Kept (theirs)').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Yours').length).toBeGreaterThan(0)
  })

  it('accepts either side for one field', async () => {
    show([conflict('c1')])
    await userEvent.click(screen.getByRole('button', { name: 'Accept yours' }))
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].path).toContain('/conflicts/c1/resolve')
    expect(posts[0].body).toMatchObject({ take: 'mine', force: false })
    await userEvent.click(screen.getByRole('button', { name: 'Accept theirs' }))
    await waitFor(() => expect(posts).toHaveLength(2))
    expect(posts[1].body).toMatchObject({ take: 'theirs' })
  })

  it('asks before overwriting a value that has moved on again', async () => {
    show([conflict('c1', { stale: true })])
    expect(screen.getByRole('status')).toHaveTextContent('changed again')
    await userEvent.click(
      screen.getByRole('button', { name: 'Accept yours anyway' }),
    )
    await waitFor(() => expect(posts[0].body).toMatchObject({ force: true }))
  })

  it('accepts a side for everything on the record at once', async () => {
    show([
      conflict('c1'),
      conflict('c2', { field: 'data.f2', field_label: 'Depth' }),
    ])
    await userEvent.click(
      screen.getByRole('button', { name: 'Accept all yours' }),
    )
    await waitFor(() =>
      expect(posts[0].body).toEqual({
        take: 'mine',
        kind: 'conflict',
        record_id: 'r1',
      }),
    )
  })

  it('edits the result with the field’s own input', async () => {
    const onSave = show([
      conflict('c1', {
        field: 'data.f2',
        dtype: 'float',
        field_label: 'Depth',
        yours: 7,
        theirs: 9,
        base: 1,
      }),
    ])
    const row = screen.getByRole('group', { name: 'Depth' })
    await userEvent.click(within(row).getByTitle('Click to edit'))
    await userEvent.keyboard('{Control>}a{/Control}12{Enter}')
    await waitFor(() => expect(onSave).toHaveBeenCalledWith('depth', 12))
  })

  it('keeps a settled row on screen, saying how, and can take keeping theirs back', async () => {
    show([
      conflict('c1', {
        status: 'resolved',
        resolution: 'theirs',
        resolved_at: '2026-10-05T10:05:00Z',
      }),
    ])
    expect(screen.getByText('Kept theirs')).toBeInTheDocument()
    expect(
      screen.getByText('Everything on this record is settled.'),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Accept yours' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Undo' }))
    await waitFor(() => expect(posts[0].path).toContain('/conflicts/reopen'))
  })

  it('shows a refused change as the field to fix, not two sides', async () => {
    show([
      conflict('c1', {
        kind: 'rejected',
        field: 'data.f2',
        attempted: 'create',
        message: "Field 'depth': must be under 5",
        takes: ['theirs', 'retry'],
        changes: [],
      }),
    ])
    expect(screen.getByText('Not on the server yet')).toBeInTheDocument()
    expect(screen.getByText(/must be under 5/)).toBeInTheDocument()
    expect(
      screen.getByText(/Saving sends the record again/),
    ).toBeInTheDocument()
    expect(screen.queryByText('Before your change')).not.toBeInTheDocument()
    expect(screen.queryByText('Your change')).not.toBeInTheDocument()
    await userEvent.click(
      screen.getByRole('button', { name: 'Send unchanged' }),
    )
    await waitFor(() => expect(posts[0].body).toMatchObject({ take: 'retry' }))
  })

  it('says a refusal sent again is on its way, and keeps it open', () => {
    show([
      conflict('c1', {
        kind: 'rejected',
        field: 'data.f2',
        attempted: 'create',
        message: 'refused',
        resolution: 'retrying',
        takes: ['theirs'],
        changes: [],
      }),
    ])
    expect(screen.getByText('Sending again…')).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Send unchanged' }),
    ).not.toBeInTheDocument()
  })

  it('shows an edit against a delete with its two choices', () => {
    show([
      conflict('c1', {
        kind: 'edit_vs_delete',
        field: null,
        attempted: 'update',
        theirs_actor: 'laptop',
        takes: ['theirs', 'delete'],
      }),
    ])
    expect(screen.getByText(/deleted elsewhere \(laptop/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Keep it' })).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Delete it' }),
    ).toBeInTheDocument()
  })

  it('says so when there is nothing to settle', () => {
    show([])
    expect(
      screen.getByText('Nothing to settle on this record'),
    ).toBeInTheDocument()
  })
})
