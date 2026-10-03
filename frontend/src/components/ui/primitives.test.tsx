import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { Button } from './Button'
import { Card } from './Card'
import { InfoTip, Tooltip } from './Tooltip'
import { SortableList } from './SortableList'
import { IconButton } from './IconButton'
import { Info } from './icons'

describe('Tooltip / InfoTip', () => {
  it('shows tooltip text on focus and links it to the trigger', async () => {
    render(
      <Tooltip content="Explains it">
        <button>Go</button>
      </Tooltip>,
    )
    expect(screen.queryByRole('tooltip')).toBeNull()
    await userEvent.tab()
    const tip = screen.getByRole('tooltip')
    expect(tip).toHaveTextContent('Explains it')
    expect(screen.getByRole('button', { name: 'Go' })).toHaveAttribute(
      'aria-describedby',
      tip.id,
    )
  })

  it('InfoTip toggles on click and closes on Escape', async () => {
    render(<InfoTip>Some detail</InfoTip>)
    await userEvent.click(
      screen.getByRole('button', { name: 'More information' }),
    )
    expect(screen.getByRole('tooltip')).toHaveTextContent('Some detail')
    await userEvent.keyboard('{Escape}')
    await userEvent.unhover(
      screen.getByRole('button', { name: 'More information' }),
    )
    expect(screen.queryByRole('tooltip')).toBeNull()
  })

  it('IconButton keeps its label as a tooltip', async () => {
    render(<IconButton icon={Info} aria-label="Details" />)
    await userEvent.hover(screen.getByRole('button', { name: 'Details' }))
    expect(screen.getByRole('tooltip')).toHaveTextContent('Details')
  })
})

describe('Button', () => {
  it('renders a link, not a button, when given `to`', () => {
    render(
      <MemoryRouter>
        <Button to="/x">Open</Button>
      </MemoryRouter>,
    )
    expect(screen.getByRole('link', { name: 'Open' })).toHaveAttribute(
      'href',
      '/x',
    )
    expect(screen.queryByRole('button')).toBeNull()
  })
})

describe('Card', () => {
  it('makes the whole card a link when interactive', () => {
    render(
      <MemoryRouter>
        <Card to="/c" title="Schemas">
          body
        </Card>
      </MemoryRouter>,
    )
    expect(screen.getByRole('link', { name: /Schemas/ })).toHaveAttribute(
      'href',
      '/c',
    )
  })
})

describe('SortableList', () => {
  it('reorders with Alt+Arrow and the move buttons', async () => {
    const onReorder = vi.fn()
    render(
      <SortableList
        label="Things"
        items={['a', 'b', 'c']}
        getKey={(x) => x}
        getLabel={(x) => x}
        moveButtons="always"
        onReorder={onReorder}
        renderItem={(x) => <span tabIndex={0}>{x}</span>}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Move a down' }))
    expect(onReorder.mock.calls[0][0]).toEqual(['b', 'a', 'c'])
    screen.getByText('c').focus()
    await userEvent.keyboard('{Alt>}{ArrowUp}{/Alt}')
    expect(onReorder.mock.calls[1][0]).toEqual(['a', 'c', 'b'])
    expect(screen.getByRole('status')).toHaveTextContent(
      'c moved to position 2 of 3.',
    )
  })
})
