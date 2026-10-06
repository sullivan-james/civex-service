import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import type { AuditLogEntry } from '../../api/audit'
import type { SyncConflict } from '../../api/remote'
import { SyncBadge, SyncOutcome } from './SyncOutcome'

function conflict(extra: Partial<SyncConflict> = {}): SyncConflict {
  return {
    id: 'c1',
    kind: 'conflict',
    entity_type: 'record',
    entity_id: 'r1',
    field: 'data.f1',
    yours: 'north reef camp',
    theirs: 'south reef camp',
    base: 'reef camp',
    theirs_actor: 'laptop',
    theirs_at: null,
    status: 'open',
    resolution: null,
    resolved_at: null,
    field_label: 'Site',
    dtype: 'string',
    record_deleted: false,
    message: null,
    attempted: null,
    changes: [],
    takes: ['theirs', 'mine'],
    ...extra,
  } as SyncConflict
}

const entry = (sync: SyncConflict[]) =>
  ({ id: 'e1', action: 'update', sync }) as unknown as AuditLogEntry

const show = (ui: React.ReactNode) => render(<MemoryRouter>{ui}</MemoryRouter>)

describe('SyncBadge', () => {
  it('says nothing for a change that went in as made', () => {
    const { container } = show(<SyncBadge entry={entry([])} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('says what is still open, and counts several', () => {
    show(<SyncBadge entry={entry([conflict(), conflict({ id: 'c2' })])} />)
    expect(screen.getByText('Clashed · 2')).toBeInTheDocument()
  })

  it('says it is settled once nothing is open', () => {
    show(
      <SyncBadge
        entry={entry([conflict({ status: 'resolved', resolution: 'theirs' })])}
      />,
    )
    expect(screen.getByText('Sync: settled')).toBeInTheDocument()
  })
})

describe('SyncOutcome', () => {
  it('shows a clash with each side’s differing words marked, and a way into the record', () => {
    show(<SyncOutcome entry={entry([conflict()])} />)
    expect(screen.getByText('south').tagName).toBe('MARK')
    expect(screen.getByText('north').tagName).toBe('MARK')
    expect(screen.getByText('Still to settle')).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: 'Resolve side by side' }),
    ).toHaveAttribute('href', '/records/r1?tab=resolve')
  })

  it('says how a settled one ended, with no way to settle it again', () => {
    show(
      <SyncOutcome
        entry={entry([
          conflict({
            status: 'resolved',
            resolution: 'mine',
            resolved_at: '2026-10-05T10:05:00Z',
          }),
        ])}
      />,
    )
    expect(screen.getByText(/Used yours/)).toBeInTheDocument()
    expect(
      screen.queryByRole('link', { name: 'Resolve side by side' }),
    ).toBeNull()
  })

  it('shows a refused change with its reason and before and after', () => {
    show(
      <SyncOutcome
        entry={entry([
          conflict({
            kind: 'rejected',
            field: null,
            attempted: 'update',
            message: 'depth must be under 5',
            changes: [
              {
                field_id: 'f2',
                field_name: 'depth',
                field_label: 'Depth',
                dtype: 'float',
                before: 1,
                after: 9,
                current: 9,
              },
            ],
          }),
        ])}
      />,
    )
    expect(
      screen.getByText(/Your change to this record was refused/),
    ).toBeInTheDocument()
    expect(screen.getByText('Depth')).toBeInTheDocument()
  })

  it('shows nothing for a change that went in as made', () => {
    const { container } = show(<SyncOutcome entry={entry([])} />)
    expect(container).toBeEmptyDOMElement()
  })
})
