import { describe, expect, it, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SplitPane } from './SplitPane'

beforeEach(() => localStorage.clear())

const pane = (side: boolean) => (
  <SplitPane
    storageKey="test.width"
    label="Charts"
    main={<p>records</p>}
    side={side ? <p>charts</p> : undefined}
    initial={300}
    min={200}
    max={400}
  />
)

describe('SplitPane', () => {
  it('resizes from the keyboard within its limits and remembers the width', async () => {
    const user = userEvent.setup()
    const first = render(pane(true))
    const divider = screen.getByRole('separator', { name: 'Resize Charts' })
    expect(divider).toHaveAttribute('aria-valuenow', '300')
    divider.focus()
    await user.keyboard('{ArrowLeft}')
    expect(divider).toHaveAttribute('aria-valuenow', '316')
    await user.keyboard('{End}')
    expect(divider).toHaveAttribute('aria-valuenow', '400')
    await user.keyboard('{ArrowLeft}')
    expect(divider).toHaveAttribute('aria-valuenow', '400')
    await user.keyboard('{Home}{ArrowRight}')
    expect(divider).toHaveAttribute('aria-valuenow', '200')
    first.unmount()
    render(pane(true))
    expect(screen.getByRole('separator')).toHaveAttribute(
      'aria-valuenow',
      '200',
    )
  })

  it('gives the main pane everything when there is no side', () => {
    render(pane(false))
    expect(screen.getByText('records')).toBeInTheDocument()
    expect(screen.queryByRole('separator')).toBeNull()
  })
})
