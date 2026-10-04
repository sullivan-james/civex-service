import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ColumnPicker } from './ColumnPicker'
import type { ResolvedField } from '../../utils/viewFields'

const field = (name: string) =>
  ({ name, label: null }) as unknown as ResolvedField
const FIELDS = ['a', 'b', 'c', 'd', 'e'].map(field)

function setup(columns: string[]) {
  const onChange = vi.fn()
  render(
    <ColumnPicker
      columns={columns}
      onChange={onChange}
      baseFields={FIELDS}
      joinable={[]}
    />,
  )
  return onChange
}

// The picker has a box per field on the left and a remove button per chosen one
// on the right, so find the boxes by the field they sit beside.
const box = (label: string) =>
  screen.getByText(label, { selector: 'label' }).querySelector('input')!

describe('ColumnPicker', () => {
  it('adds one column per plain click', async () => {
    const onChange = setup([])
    await userEvent.click(box('A'))
    expect(onChange).toHaveBeenLastCalledWith(['a'])
  })

  it('adds every column between two with shift-click, in the order shown', async () => {
    const onChange = setup([])
    const user = userEvent.setup()

    await user.click(box('B'))
    await user.keyboard('{Shift>}')
    await user.click(box('D'))
    await user.keyboard('{/Shift}')

    // (The picker is controlled and not re-rendered here, so the first click's
    // own change is not in `columns`; the range is what matters.)
    expect(onChange).toHaveBeenLastCalledWith(['b', 'c', 'd'])
  })

  it('removes a run of columns with shift-click when the box is being unticked', async () => {
    const onChange = setup(['a', 'b', 'c', 'd', 'e'])
    const user = userEvent.setup()

    await user.click(box('B'))
    await user.keyboard('{Shift>}')
    await user.click(box('D'))
    await user.keyboard('{/Shift}')

    expect(onChange).toHaveBeenLastCalledWith(['a', 'e'])
  })

  it('keeps columns already chosen where they are when adding a range', async () => {
    const onChange = setup(['c', 'a'])
    const user = userEvent.setup()

    await user.click(box('B')) // ticks b
    await user.keyboard('{Shift>}')
    await user.click(box('E'))
    await user.keyboard('{/Shift}')

    // c and a keep their order; the new ones follow in the order shown.
    expect(onChange).toHaveBeenLastCalledWith(['c', 'a', 'b', 'd', 'e'])
  })
})

describe('ColumnPicker: clicking the label text, as people do', () => {
  it('shift-click on a column name adds the whole range', async () => {
    const onChange = setup([])
    const user = userEvent.setup()

    // The name, not the little box: the browser then clicks the box for us, and
    // that second click may not say shift was held.
    await user.click(screen.getByText('B', { selector: 'label' }))
    await user.keyboard('{Shift>}')
    await user.click(screen.getByText('D', { selector: 'label' }))
    await user.keyboard('{/Shift}')

    expect(onChange).toHaveBeenLastCalledWith(['b', 'c', 'd'])
  })
})
