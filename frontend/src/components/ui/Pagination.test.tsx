import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router'
import { useListParams } from '../../hooks/useListParams'
import { Pagination } from './Pagination'

describe('Pagination', () => {
  it('reports a new page size once, and leaves going back to page one to that one call', async () => {
    const onPage = vi.fn()
    const onPageSize = vi.fn()
    render(
      <Pagination
        page={3}
        pageSize={25}
        total={500}
        onPage={onPage}
        onPageSize={onPageSize}
      />,
    )

    await userEvent.selectOptions(screen.getByLabelText('Rows'), '100')

    expect(onPageSize).toHaveBeenCalledExactlyOnceWith(100)
    // A second update in the same event would undo the first one when the
    // page lives in the address.
    expect(onPage).not.toHaveBeenCalled()
  })

  it('still moves between pages', async () => {
    const onPage = vi.fn()
    render(
      <Pagination
        page={1}
        pageSize={25}
        total={100}
        onPage={onPage}
        onPageSize={() => {}}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: 'Next page' }))
    await userEvent.click(screen.getByRole('button', { name: 'Previous page' }))

    expect(onPage.mock.calls).toEqual([[2], [0]])
  })
})

/** A list whose page and size live in the address, as the runs and history
 * tables do. */
function AddressList() {
  const list = useListParams('', [])
  const where = useLocation()
  return (
    <>
      <p data-testid="rows">{list.size} rows</p>
      <p data-testid="page">page {list.page + 1}</p>
      <p data-testid="address">{where.search}</p>
      <Pagination
        page={list.page}
        pageSize={list.size}
        total={500}
        onPage={(page) => list.set({ page })}
        onPageSize={(size) => list.set({ size })}
      />
    </>
  )
}

describe('Pagination in a list held in the address', () => {
  it('changes how many rows are shown, and goes back to page one', async () => {
    render(
      <MemoryRouter initialEntries={['/runs?page=4']}>
        <AddressList />
      </MemoryRouter>,
    )
    expect(screen.getByTestId('page')).toHaveTextContent('page 4')

    await userEvent.selectOptions(screen.getByLabelText('Rows'), '100')

    expect(screen.getByTestId('rows')).toHaveTextContent('100 rows')
    expect(screen.getByTestId('page')).toHaveTextContent('page 1')
    expect(screen.getByTestId('address')).toHaveTextContent('size=100')
  })

  it('keeps the new size when moving to another page afterwards', async () => {
    render(
      <MemoryRouter initialEntries={['/runs']}>
        <AddressList />
      </MemoryRouter>,
    )

    await userEvent.selectOptions(screen.getByLabelText('Rows'), '50')
    await userEvent.click(screen.getByRole('button', { name: 'Next page' }))

    expect(screen.getByTestId('rows')).toHaveTextContent('50 rows')
    expect(screen.getByTestId('page')).toHaveTextContent('page 2')
  })
})
