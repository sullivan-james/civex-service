import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { EditableCell } from './EditableCell'
import type { Field } from '../../api/schemas'

function field(type: string, extra: Partial<Field> = {}): Field {
  return {
    id: 'f',
    name: 'weight',
    label: null,
    type,
    required: false,
    restrictions: {},
    default: null,
    position: 0,
    ...extra,
  }
}

function renderCell(
  f: Field,
  value: unknown,
  onCommit: (v: unknown) => Promise<void> | void = vi.fn(),
) {
  render(
    <table>
      <tbody>
        <tr>
          <EditableCell
            field={f}
            value={value}
            onCommit={onCommit}
            rowLabel="r1"
          />
        </tr>
      </tbody>
    </table>,
  )
  return onCommit
}

const cell = () => screen.getByRole('cell', { name: /Edit Weight, r1/i })

describe('EditableCell inline editing', () => {
  it('click edits, Enter commits the coerced value', async () => {
    const onCommit = renderCell(field('integer'), 3)
    await userEvent.click(cell())
    const input = screen.getByRole('spinbutton')
    expect(input).toHaveFocus()
    fireEvent.change(input, { target: { value: '9' } })
    await userEvent.keyboard('{Enter}')
    expect(onCommit).toHaveBeenCalledWith(9)
    await waitFor(() => expect(screen.queryByRole('spinbutton')).toBeNull())
    expect(cell()).toHaveFocus()
  })

  it('Escape cancels without committing', async () => {
    const onCommit = renderCell(field('string'), 'a')
    await userEvent.click(cell())
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'zzz' } })
    await userEvent.keyboard('{Escape}')
    expect(onCommit).not.toHaveBeenCalled()
    expect(screen.queryByRole('textbox')).toBeNull()
  })

  it('does not commit when the value is unchanged', async () => {
    const onCommit = renderCell(field('string'), 'a')
    await userEvent.click(cell())
    await userEvent.keyboard('{Enter}')
    expect(onCommit).not.toHaveBeenCalled()
  })

  it('clicking away commits', async () => {
    const onCommit = renderCell(field('string'), 'a')
    await userEvent.click(cell())
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'b' } })
    await userEvent.click(document.body)
    expect(onCommit).toHaveBeenCalledWith('b')
  })

  it('clearing a field commits undefined', async () => {
    const onCommit = renderCell(field('string'), 'a')
    await userEvent.click(cell())
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '' } })
    await userEvent.keyboard('{Enter}')
    expect(onCommit).toHaveBeenCalledWith(undefined)
  })

  it('keeps editing and shows the error when the commit rejects', async () => {
    const onCommit = vi.fn().mockRejectedValue(new Error('must be >= 1'))
    renderCell(field('integer'), 3, onCommit)
    await userEvent.click(cell())
    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '0' } })
    await userEvent.keyboard('{Enter}')
    expect(await screen.findByRole('alert')).toHaveTextContent('must be >= 1')
    expect(screen.getByRole('spinbutton')).toHaveValue(0)
  })

  it('opens from the keyboard with Enter or F2', async () => {
    renderCell(field('string'), 'a')
    cell().focus()
    await userEvent.keyboard('{F2}')
    expect(screen.getByRole('textbox')).toBeInTheDocument()
  })

  it('toggles booleans directly', async () => {
    const onCommit = renderCell(field('boolean'), false)
    await userEvent.click(screen.getByRole('checkbox'))
    expect(onCommit).toHaveBeenCalledWith(true)
  })

  it('is inert when disabled', async () => {
    render(
      <table>
        <tbody>
          <tr>
            <EditableCell
              field={field('string')}
              value="a"
              onCommit={vi.fn()}
              disabled
            />
          </tr>
        </tbody>
      </table>,
    )
    await userEvent.click(screen.getByRole('cell'))
    expect(screen.queryByRole('textbox')).toBeNull()
  })
})

describe('EditableCell popover editing', () => {
  it('opens a dialog for file fields; Cancel closes without committing', async () => {
    const onCommit = renderCell(field('file'), null)
    await userEvent.click(cell())
    expect(
      screen.getByRole('dialog', { name: /Edit Weight/ }),
    ).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(onCommit).not.toHaveBeenCalled()
  })

  it('Escape closes the popover', async () => {
    renderCell(field('file_list'), [])
    await userEvent.click(cell())
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('is portalled outside the table so cell clipping cannot cut it off', async () => {
    renderCell(field('file'), null)
    await userEvent.click(cell())
    expect(screen.getByRole('dialog').closest('table')).toBeNull()
  })
})
