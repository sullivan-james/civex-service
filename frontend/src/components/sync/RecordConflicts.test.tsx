import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import type { SyncConflict } from '../../api/remote'
import { layoutConflicts } from '../../utils/syncConflicts'
import { RecordConflicts } from './RecordConflicts'

const FIELDS = [{ id: 'f1', name: 'site' }]

function conflict(extra: Partial<SyncConflict> = {}): SyncConflict {
  return {
    id: 'c1',
    kind: 'conflict',
    entity_type: 'record',
    entity_id: 'r1',
    field: 'data.f1',
    theirs_actor: null,
    theirs_at: null,
    message: null,
    attempted: null,
    changes: [],
    ...extra,
  } as SyncConflict
}

function show(conflicts: SyncConflict[], onResolve = vi.fn()) {
  render(
    <MemoryRouter>
      <RecordConflicts
        layout={layoutConflicts(conflicts, FIELDS)}
        onResolve={onResolve}
      />
    </MemoryRouter>,
  )
  return onResolve
}

describe('RecordConflicts', () => {
  it('says nothing while there is nothing to review', () => {
    show([])
    expect(screen.queryByRole('region')).toBeNull()
  })

  it('counts them and opens the side-by-side view', async () => {
    const open = show([conflict(), conflict({ id: 'c2' })])
    expect(
      screen.getByText('2 of your changes to this record were not applied'),
    ).toBeInTheDocument()
    await userEvent.click(
      screen.getByRole('button', { name: 'Resolve side by side' }),
    )
    expect(open).toHaveBeenCalled()
  })

  it('says why a refused change was refused', () => {
    show([
      conflict({
        kind: 'rejected',
        field: null,
        attempted: 'create',
        message: 'site "z" is already used',
      }),
    ])
    expect(
      screen.getByText(/This record isn't on the server yet/),
    ).toBeInTheDocument()
    expect(screen.getByText(/already used/)).toBeInTheDocument()
  })

  it('says who deleted what an edit met', () => {
    show([
      conflict({
        kind: 'edit_vs_delete',
        field: null,
        attempted: 'update',
        theirs_actor: 'laptop',
      }),
    ])
    expect(screen.getByText(/deleted elsewhere \(laptop/)).toBeInTheDocument()
  })
})
