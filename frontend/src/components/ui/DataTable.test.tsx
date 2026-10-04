import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { DataTable } from './DataTable'

interface Row {
  id: string
  name: string
}
const ROWS: Row[] = [
  { id: 'a', name: 'Alpha' },
  { id: 'b', name: 'Beta' },
]
const COLUMNS = [
  { key: 'name', header: 'Name', sortable: true },
  { key: 'id', header: 'Id', render: (r: Row) => <button>open {r.id}</button> },
]

describe('DataTable', () => {
  it('follows the row link when any non-interactive part of the row is clicked', async () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route
            path="/"
            element={
              <DataTable
                columns={COLUMNS}
                rows={ROWS}
                getRowId={(r) => r.id}
                rowHref={(r) => `/things/${r.id}`}
              />
            }
          />
          <Route path="/things/:id" element={<p>thing page</p>} />
        </Routes>
      </MemoryRouter>,
    )
    expect(screen.getByRole('link', { name: /Alpha/ })).toHaveAttribute(
      'href',
      '/things/a',
    )
    // The Id cell is far from the link; clicking its padding still navigates.
    await userEvent.click(screen.getAllByRole('cell')[1])
    expect(await screen.findByText('thing page')).toBeInTheDocument()
  })

  it('leaves buttons inside a clickable row alone', async () => {
    const onRowClick = vi.fn()
    const onButton = vi.fn()
    render(
      <DataTable
        columns={[
          {
            key: 'x',
            header: 'X',
            render: (r: Row) => <button onClick={onButton}>b {r.id}</button>,
          },
        ]}
        rows={ROWS}
        getRowId={(r) => r.id}
        onRowClick={onRowClick}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'b a' }))
    expect(onButton).toHaveBeenCalledTimes(1)
    expect(onRowClick).not.toHaveBeenCalled()
    await userEvent.click(screen.getAllByRole('cell')[0])
    expect(onRowClick).toHaveBeenCalledWith(ROWS[0])
  })

  it('shows row actions without hovering, selects rows, and sorts', async () => {
    const onToggle = vi.fn()
    const onSort = vi.fn()
    render(
      <DataTable
        columns={COLUMNS}
        rows={ROWS}
        getRowId={(r) => r.id}
        actions={(r) => <button>act {r.id}</button>}
        selection={{
          selected: new Set(['b']),
          onToggle,
          onToggleAll: vi.fn(),
          rowLabel: (id) => `pick ${id}`,
        }}
        onSortChange={onSort}
      />,
    )
    expect(screen.getByRole('button', { name: 'act a' })).toBeVisible()
    expect(screen.getByLabelText('pick b')).toBeChecked()
    await userEvent.click(screen.getByLabelText('pick a'))
    expect(onToggle).toHaveBeenCalledWith('a')
    await userEvent.click(screen.getByRole('button', { name: 'Name' }))
    expect(onSort).toHaveBeenCalledWith('name')
  })

  it('shows the empty state with its action', () => {
    render(
      <DataTable
        columns={COLUMNS}
        rows={[]}
        getRowId={(r: Row) => r.id}
        emptyTitle="Nothing"
        emptyAction={<button>Make one</button>}
      />,
    )
    const status = screen.getByRole('status')
    expect(within(status).getByText('Nothing')).toBeInTheDocument()
    expect(
      within(status).getByRole('button', { name: 'Make one' }),
    ).toBeInTheDocument()
  })
})
