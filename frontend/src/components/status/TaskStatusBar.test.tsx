import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { AlertTriangle, HardDrive } from '../ui/icons'
import type { BackgroundTask } from '../../utils/backgroundTasks'
import { barPercent } from '../../utils/backgroundTasks'
import { StatusBar } from './TaskStatusBar'

const task = (over: Partial<BackgroundTask> = {}): BackgroundTask => ({
  id: 't1',
  tone: 'info',
  icon: HardDrive,
  title: 'Doing something',
  ...over,
})

const renderBar = (tasks: BackgroundTask[]) =>
  render(
    <MemoryRouter>
      <StatusBar tasks={tasks} />
    </MemoryRouter>,
  )

describe('StatusBar (the generic bottom bar)', () => {
  it('renders nothing when there is nothing going on', () => {
    const { container } = renderBar([])
    expect(container).toBeEmptyDOMElement()
  })

  it('shows any task by what it says about itself, knowing nothing of its kind', () => {
    renderBar([
      task({
        title: 'Importing Selections',
        detail: '40 of 100 rows',
        note: '2 more waiting',
      }),
    ])

    expect(screen.getByText('Importing Selections')).toBeInTheDocument()
    expect(screen.getByText('40 of 100 rows')).toBeInTheDocument()
    expect(screen.getByText('2 more waiting')).toBeInTheDocument()
  })

  it('draws a bar only for a task that can say how far along it is', () => {
    renderBar([
      task({
        id: 'a',
        title: 'Known',
        progress: { fraction: 0.4, label: 'Known progress' },
      }),
      task({ id: 'b', title: 'Unknown' }),
    ])

    const bars = screen.getAllByRole('progressbar')
    expect(bars).toHaveLength(1)
    expect(bars[0]).toHaveAttribute('aria-label', 'Known progress')
    expect(bars[0]).toHaveAttribute('aria-valuenow', '40')
  })

  it('keeps a bar inside its range', () => {
    expect(barPercent(-1)).toBe(0)
    expect(barPercent(0.5)).toBe(50)
    expect(barPercent(7)).toBe(100)
  })

  it('stacks several tasks in one bar, a row each', () => {
    renderBar([
      task({ id: 'a', title: 'First thing' }),
      task({
        id: 'b',
        title: 'Second thing',
        tone: 'attention',
        icon: AlertTriangle,
      }),
    ])

    const bar = screen.getByRole('status')
    expect(within(bar).getByText('First thing')).toBeInTheDocument()
    expect(within(bar).getByText('Second thing')).toBeInTheDocument()
  })

  it('makes an action with an address a link, and one without a button that acts', async () => {
    const onClick = vi.fn()
    renderBar([
      task({
        actions: [
          { label: 'Details', to: '/somewhere' },
          { label: 'Pause', onClick },
          { label: 'Busy', disabled: true },
        ],
      }),
    ])

    expect(screen.getByRole('link', { name: 'Details' })).toHaveAttribute(
      'href',
      '/somewhere',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Pause' }))
    expect(onClick).toHaveBeenCalledOnce()
    expect(screen.getByRole('button', { name: 'Busy' })).toBeDisabled()
  })

  it('draws a task’s overlay (the dialog one of its actions opens) with the bar', () => {
    renderBar([task({ overlay: <p>Are you sure?</p> })])
    expect(screen.getByText('Are you sure?')).toBeInTheDocument()
  })
})
