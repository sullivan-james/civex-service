import { describe, it, expect } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import { useRef, useState } from 'react'
import { useDialogA11y } from './useDialogA11y'

/** An overlay mounted only while it is open, like the navigation drawer:
 * by the time the effect's cleanup runs, it has already left the page. */
function Page() {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  useDialogA11y({ open, onClose: () => setOpen(false), rootRef })
  return (
    <div>
      <main data-testid="main">
        <button onClick={() => setOpen(true)}>Open</button>
      </main>
      <aside data-testid="aside" />
      {open && (
        <div ref={rootRef} data-testid="drawer">
          <button onClick={() => setOpen(false)}>Go somewhere</button>
        </div>
      )}
    </div>
  )
}

describe('useDialogA11y', () => {
  it('makes the page behind an open overlay inert', () => {
    render(<Page />)
    act(() => screen.getByText('Open').click())
    expect(screen.getByTestId('main').inert).toBe(true)
  })

  it('gives the page back when an overlay that unmounts on close closes', () => {
    // The drawer freeze: closing removed the drawer before the cleanup ran,
    // so the cleanup couldn't find the page to restore and it stayed inert.
    render(<Page />)
    act(() => screen.getByText('Open').click())
    act(() => screen.getByText('Go somewhere').click())
    expect(screen.queryByTestId('drawer')).toBeNull()
    expect(screen.getByTestId('main').inert).toBe(false)
  })

  it('leaves alone what was inert before it opened', () => {
    render(<Page />)
    // Set as a browser reflects the attribute (jsdom doesn't reflect it).
    screen.getByTestId('aside').inert = true
    act(() => screen.getByText('Open').click())
    act(() => screen.getByText('Go somewhere').click())
    expect(screen.getByTestId('main').inert).toBe(false)
    expect(screen.getByTestId('aside').inert).toBe(true)
  })
})
