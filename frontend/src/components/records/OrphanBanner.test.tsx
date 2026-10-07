import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { CivexRecord } from '../../api/records'
import { recordsApi } from '../../api/records'
import { ToastProvider } from '../ui'
import { OrphanBanner } from './OrphanBanner'

const record = (over: Partial<CivexRecord>): CivexRecord =>
  ({
    id: 's1',
    schema_name: 'Selection',
    data: {},
    ...over,
  }) as CivexRecord

function show(r: CivexRecord, onDelete = vi.fn()) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ToastProvider>
        <OrphanBanner record={r} onDelete={onDelete} />
      </ToastProvider>
    </QueryClientProvider>,
  )
  return onDelete
}

afterEach(() => vi.restoreAllMocks())

describe('OrphanBanner', () => {
  it('says nothing for a record whose parents are live', () => {
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <ToastProvider>
          <OrphanBanner
            record={record({ deleted_above: [] })}
            onDelete={vi.fn()}
          />
        </ToastProvider>
      </QueryClientProvider>,
    )
    expect(container.querySelector('[role=alert]')).toBeNull()
  })

  it('says what a record sits under, and restores it or deletes the record', async () => {
    const restore = vi.spyOn(recordsApi, 'restoreAbove').mockResolvedValue([])
    const onDelete = show(
      record({
        deleted_above: [
          { id: 'r1', schema_name: 'Recording', natural_name: '2026-11-06' },
        ],
      }),
    )
    expect(
      screen.getByText(
        'This Selection sits under Recording 2026-11-06, which is deleted.',
      ),
    ).toBeInTheDocument()
    await userEvent.click(
      screen.getByRole('button', { name: 'Restore Recording 2026-11-06' }),
    )
    await waitFor(() => expect(restore).toHaveBeenCalledWith('s1'))
    await userEvent.click(
      screen.getByRole('button', { name: 'Delete this Selection' }),
    )
    expect(onDelete).toHaveBeenCalled()
  })
})
