import { describe, it, expect, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Menu, type MenuEntry } from './Menu'
import { Archive, FolderOpen } from './icons'

function renderMenu(items: MenuEntry[], wide = false) {
  render(
    <Menu
      items={items}
      wide={wide}
      trigger={({ toggle }) => <button onClick={toggle}>Open</button>}
    />,
  )
  return userEvent.click(screen.getByRole('button', { name: 'Open' }))
}

describe('Menu', () => {
  it('lists its items and runs one, closing itself', async () => {
    const run = vi.fn()
    await renderMenu([{ label: 'Do it', onClick: run }])

    await userEvent.click(screen.getByRole('menuitem', { name: 'Do it' }))

    expect(run).toHaveBeenCalledOnce()
    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('groups items under headings that are not themselves actions', async () => {
    await renderMenu([
      { heading: 'First' },
      { label: 'A', onClick: () => {} },
      { heading: 'Second' },
      { label: 'B', onClick: () => {} },
    ])

    const menu = screen.getByRole('menu')
    expect(within(menu).getByText('First')).toBeTruthy()
    expect(within(menu).getByText('Second')).toBeTruthy()
    expect(within(menu).getAllByRole('menuitem')).toHaveLength(2)
  })

  it('separates groups with a rule', async () => {
    await renderMenu([
      { label: 'A', onClick: () => {} },
      { separator: true },
      { label: 'B', onClick: () => {} },
    ])

    expect(
      within(screen.getByRole('menu')).getAllByRole('separator'),
    ).toHaveLength(1)
  })

  it('draws every icon the same size in the same box', async () => {
    await renderMenu([
      { label: 'A', icon: FolderOpen, onClick: () => {} },
      { label: 'B', hint: 'with a hint', icon: Archive, onClick: () => {} },
    ])

    const svgs = screen
      .getAllByRole('menuitem')
      .map((i) => i.querySelector('svg')!)
    expect(svgs.map((s) => s.getAttribute('width'))).toEqual(['18', '18'])
    expect(svgs[0].parentElement!.className).toBe(
      svgs[1].parentElement!.className,
    )
  })

  it('puts a hint under its label', async () => {
    await renderMenu([{ label: 'A', hint: 'what it does', onClick: () => {} }])

    const item = screen.getByRole('menuitem')
    expect(within(item).getByText('A')).toBeTruthy()
    expect(within(item).getByText('what it does')).toBeTruthy()
  })

  it('can be wide, for items that explain themselves', async () => {
    await renderMenu([{ label: 'A', hint: 'h', onClick: () => {} }], true)

    expect(screen.getByRole('menu').className).toMatch(/w-80/)
  })

  it('does not run a disabled item', async () => {
    const run = vi.fn()
    await renderMenu([{ label: 'A', disabled: true, onClick: run }])

    await userEvent.click(screen.getByRole('menuitem', { name: 'A' }))

    expect(run).not.toHaveBeenCalled()
  })

  it('closes on Escape', async () => {
    await renderMenu([{ label: 'A', onClick: () => {} }])

    await userEvent.keyboard('{Escape}')

    expect(screen.queryByRole('menu')).toBeNull()
  })
})
