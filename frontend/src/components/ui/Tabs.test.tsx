import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Tabs } from './Tabs'

const TABS = [
  { id: 'a', label: 'Alpha' },
  { id: 'b', label: 'Beta' },
  { id: 'c', label: 'Gamma' },
] as const

describe('Tabs', () => {
  it('marks the selected tab and only it is tabbable', () => {
    render(
      <Tabs label="Things" tabs={[...TABS]} value="b" onChange={vi.fn()} />,
    )

    expect(screen.getByRole('tablist', { name: 'Things' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Beta' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(screen.getByRole('tab', { name: 'Alpha' })).toHaveAttribute(
      'aria-selected',
      'false',
    )
    expect(screen.getByRole('tab', { name: 'Beta' })).toHaveAttribute(
      'tabindex',
      '0',
    )
    expect(screen.getByRole('tab', { name: 'Alpha' })).toHaveAttribute(
      'tabindex',
      '-1',
    )
    expect(screen.getByRole('tab', { name: 'Beta' })).toHaveAttribute(
      'aria-controls',
      'panel-b',
    )
  })

  it('changes on click and with the arrow keys, wrapping round', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(
      <Tabs label="Things" tabs={[...TABS]} value="a" onChange={onChange} />,
    )

    await user.click(screen.getByRole('tab', { name: 'Gamma' }))
    expect(onChange).toHaveBeenLastCalledWith('c')

    // Focus moves with the key, so each press starts from where the last ended.
    screen.getByRole('tab', { name: 'Alpha' }).focus()
    await user.keyboard('{ArrowLeft}')
    expect(onChange).toHaveBeenLastCalledWith('c')
    await user.keyboard('{ArrowRight}')
    expect(onChange).toHaveBeenLastCalledWith('a')
    await user.keyboard('{End}')
    expect(onChange).toHaveBeenLastCalledWith('c')
    await user.keyboard('{Home}')
    expect(onChange).toHaveBeenLastCalledWith('a')
  })
})
