import { useEffect, useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { emptyDraft, type Draft } from '../../utils/exportBuilder'
import { JustTheTable } from './JustTheTable'

let latest: Draft
const remember = (d: Draft) => {
  latest = d
}

function Harness({
  canAddFiles = true,
  onMore = () => {},
}: {
  canAddFiles?: boolean
  onMore?: () => void
}) {
  const [draft, setDraft] = useState<Draft>({
    ...emptyDraft,
    files: false,
    tables: [{ format: 'csv', columns: ['name', 'depth'], kind: 'encounter' }],
  })
  useEffect(() => remember(draft), [draft])
  return (
    <JustTheTable
      draft={draft}
      set={(patch) => setDraft((d) => ({ ...d, ...patch }))}
      placeholder="Encounters"
      canAddFiles={canAddFiles}
      onMore={onMore}
    />
  )
}

describe('just the table', () => {
  it('says what it is: the table on screen, with its columns as they are', () => {
    render(<Harness />)

    expect(screen.getByText('The table you’re looking at')).toBeTruthy()
    expect(screen.getByText(/rows and columns shown/)).toBeTruthy()
  })

  it('lets the format and the file name change, keeping the rest of the table', async () => {
    render(<Harness />)

    await userEvent.selectOptions(screen.getByLabelText('Table format'), 'xlsx')
    await userEvent.type(screen.getByLabelText('Table file name'), 'Mine')

    expect(latest.tables).toEqual([
      {
        format: 'xlsx',
        columns: ['name', 'depth'],
        kind: 'encounter',
        name: 'Mine',
      },
    ])
    expect(screen.getByLabelText('Table file name')).toHaveAttribute(
      'placeholder',
      'Encounters',
    )
  })

  it('offers to add files or more tables, and asks for the rest when pressed', async () => {
    const onMore = vi.fn()
    render(<Harness onMore={onMore} />)

    await userEvent.click(
      screen.getByRole('button', { name: 'Add files or more tables…' }),
    )

    expect(onMore).toHaveBeenCalled()
  })

  it('only offers more tables where there are no files to add', () => {
    render(<Harness canAddFiles={false} />)

    expect(
      screen.getByRole('button', { name: 'Add more tables…' }),
    ).toBeTruthy()
    expect(screen.queryByText(/files/i)).toBeNull()
  })
})
