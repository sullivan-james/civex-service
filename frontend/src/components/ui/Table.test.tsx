import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Table, Thead, Th, Tbody, Tr, Td } from './Table'

describe('Table', () => {
  it('puts aria-sort on the column header, not a child', () => {
    render(
      <Table>
        <Thead>
          <tr>
            <Th sortDirection="desc">Name</Th>
            <Th>Plain</Th>
          </tr>
        </Thead>
      </Table>,
    )
    expect(screen.getByRole('columnheader', { name: 'Name' })).toHaveAttribute(
      'aria-sort',
      'descending',
    )
    expect(
      screen.getByRole('columnheader', { name: 'Plain' }),
    ).not.toHaveAttribute('aria-sort')
  })

  it('makes clickable rows keyboard-activatable', async () => {
    const onClick = vi.fn()
    render(
      <Table>
        <Tbody>
          <Tr onClick={onClick}>
            <Td>cell</Td>
          </Tr>
        </Tbody>
      </Table>,
    )
    await userEvent.tab()
    await userEvent.keyboard('{Enter}')
    expect(onClick).toHaveBeenCalledTimes(1)
  })
})
