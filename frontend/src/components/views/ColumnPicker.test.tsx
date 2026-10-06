import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ColumnPicker } from './ColumnPicker'
import type { JoinableColumn, ResolvedField } from '../../utils/viewFields'

const field = (name: string, source = 'trial') =>
  ({ name, label: null, sourceSchemaName: source }) as unknown as ResolvedField
const FIELDS = ['a', 'b', 'c', 'd', 'e'].map((n) => field(n))

function setup(
  columns: string[],
  extra: {
    baseFields?: ResolvedField[]
    joinable?: JoinableColumn[]
    extra?: { name: string; label: string }[]
    allowHideAll?: boolean
  } = {},
) {
  const onChange = vi.fn()
  render(
    <ColumnPicker
      columns={columns}
      onChange={onChange}
      baseFields={extra.baseFields ?? FIELDS}
      joinable={extra.joinable ?? []}
      extra={extra.extra}
      allowHideAll={extra.allowHideAll}
    />,
  )
  return onChange
}

const shown = () =>
  within(screen.getByRole('list', { name: 'Shown columns' })).getAllByRole(
    'checkbox',
  )
const notShown = (label: string) =>
  screen.getByText(label, { selector: 'label' }).querySelector('input')!

describe('ColumnPicker', () => {
  it('is one list: what is shown in its order, then what is not', () => {
    setup(['c', 'a'])

    expect(shown().map((b) => b.getAttribute('aria-label'))).toEqual([
      'Show C',
      'Show A',
    ])
    expect(screen.getByText('Shown (2)')).toBeTruthy()
    for (const label of ['B', 'D', 'E']) expect(notShown(label)).toBeTruthy()
    // A shown column is not offered again below.
    expect(screen.queryAllByLabelText('Show A')).toHaveLength(1)
  })

  it('puts a column in at the end of the shown ones with one click', async () => {
    const onChange = setup(['c', 'a'])

    await userEvent.click(notShown('B'))

    expect(onChange).toHaveBeenLastCalledWith(['c', 'a', 'b'])
  })

  it('takes a column out with its own box', async () => {
    const onChange = setup(['a', 'b', 'c'])

    await userEvent.click(screen.getByLabelText('Show B'))

    expect(onChange).toHaveBeenLastCalledWith(['a', 'c'])
  })

  it('puts in every column between two with shift-click, in the order shown', async () => {
    const onChange = setup([])
    const user = userEvent.setup()

    await user.click(notShown('B'))
    await user.keyboard('{Shift>}')
    await user.click(notShown('D'))
    await user.keyboard('{/Shift}')

    // (Controlled and not re-rendered here, so the first click's own change is
    // not in `columns`; the range is what matters.)
    expect(onChange).toHaveBeenLastCalledWith(['b', 'c', 'd'])
  })

  it('moves a column later or earlier, with the arrows', async () => {
    const onChange = setup(['a', 'b', 'c'])

    await userEvent.click(screen.getByRole('button', { name: 'Move A down' }))
    expect(onChange).toHaveBeenLastCalledWith(['b', 'a', 'c'])
    await userEvent.click(screen.getByRole('button', { name: 'Move C up' }))
    expect(onChange).toHaveBeenLastCalledWith(['a', 'c', 'b'])
  })

  it('cannot move the first up or the last down', () => {
    setup(['a', 'b'])

    expect(screen.getByRole('button', { name: 'Move A up' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Move B down' })).toBeDisabled()
  })

  it('finds a column to add by typing', async () => {
    setup(['a'], {
      baseFields: ['apple', 'banana', 'cherry'].map((n) => field(n)),
    })

    await userEvent.type(screen.getByLabelText('Find a column to add'), 'an')

    expect(screen.getByText('Banana', { selector: 'label' })).toBeTruthy()
    expect(screen.queryByText('Cherry', { selector: 'label' })).toBeNull()
  })

  it('says when nothing matches, and when everything is shown', async () => {
    setup(['a', 'b', 'c', 'd', 'e'])
    expect(screen.getByText('Every column is shown.')).toBeTruthy()
  })

  it('says so when no column is shown', () => {
    setup([])

    expect(screen.getByText(/no columns shown yet/i)).toBeTruthy()
  })

  it('shows every field, or hides all of them', async () => {
    const onChange = setup(['a'])

    await userEvent.click(
      screen.getByRole('button', { name: 'Show every field' }),
    )
    expect(onChange).toHaveBeenLastCalledWith(['a', 'b', 'c', 'd', 'e'])
    await userEvent.click(screen.getByRole('button', { name: 'Hide all' }))
    expect(onChange).toHaveBeenLastCalledWith([])
  })

  it('can leave out hiding all, where an empty list would mean the default', () => {
    setup(['a'], { allowHideAll: false })

    expect(screen.queryByRole('button', { name: 'Hide all' })).toBeNull()
  })

  it('groups fields by where they come from, once there is more than one place', () => {
    setup([], {
      baseFields: [field('rname', 'recording'), field('site', 'encounter')],
    })

    expect(screen.getByText('Fields from Recording')).toBeTruthy()
    expect(screen.getByText('Fields from Encounter')).toBeTruthy()
  })

  it('offers the record’s own columns when given them', async () => {
    const onChange = setup([], {
      extra: [
        { name: 'id', label: 'Record id' },
        { name: 'created_at', label: 'Created' },
      ],
    })

    expect(screen.getByText('The record')).toBeTruthy()
    await userEvent.click(notShown('Record id'))
    expect(onChange).toHaveBeenLastCalledWith(['id'])
  })

  it('offers the columns of a linked record, under it', async () => {
    const ref = field('customer')
    const join = {
      value: 'customer.email',
      label: 'Customer → Email',
      refField: ref,
      targetField: field('email'),
    } as unknown as JoinableColumn
    const onChange = setup([], { joinable: [join] })

    expect(screen.getByText('From the linked Customer')).toBeTruthy()
    await userEvent.click(notShown('Email'))
    expect(onChange).toHaveBeenLastCalledWith(['customer.email'])
  })

  it('shows a linked column by its full name once it is shown', () => {
    const join = {
      value: 'customer.email',
      label: 'Customer → Email',
      refField: field('customer'),
      targetField: field('email'),
    } as unknown as JoinableColumn
    setup(['customer.email'], { joinable: [join] })

    expect(screen.getByLabelText('Show Customer → Email')).toBeTruthy()
  })
})
