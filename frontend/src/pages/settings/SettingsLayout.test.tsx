import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Navigate, Route, Routes } from 'react-router'
import SettingsLayout from './SettingsLayout'

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/settings" element={<SettingsLayout />}>
          <Route index element={<Navigate to="appearance" replace />} />
          <Route path="appearance" element={<p>Appearance page</p>} />
          <Route path="storage" element={<p>Storage page</p>} />
          <Route path="map" element={<p>Map page</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

describe('SettingsLayout', () => {
  it('lists every settings area as its own page', () => {
    renderAt('/settings/storage')

    const nav = screen.getByRole('navigation', { name: 'Settings sections' })
    const names = Array.from(nav.querySelectorAll('a')).map(
      (a) => a.textContent,
    )
    expect(names).toEqual([
      'Appearance',
      'Database',
      'Storage',
      'Retention',
      'Sync',
      'Map',
      'Advanced',
    ])
    expect(screen.getByRole('link', { name: 'Storage' })).toHaveAttribute(
      'aria-current',
      'page',
    )
    expect(screen.getByRole('link', { name: 'Storage' })).toHaveAttribute(
      'href',
      '/settings/storage',
    )
  })

  it('shows one area at a time and moves between them', async () => {
    const user = userEvent.setup()
    renderAt('/settings/storage')
    expect(screen.getByText('Storage page')).toBeInTheDocument()
    expect(screen.queryByText('Map page')).not.toBeInTheDocument()

    await user.click(screen.getByRole('link', { name: 'Map' }))

    expect(screen.getByText('Map page')).toBeInTheDocument()
    expect(screen.queryByText('Storage page')).not.toBeInTheDocument()
  })

  it('opens on the first area from /settings', () => {
    renderAt('/settings')

    expect(screen.getByText('Appearance page')).toBeInTheDocument()
  })
})
