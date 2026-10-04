import { describe, it, expect, afterEach } from 'vitest'
import { render } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import SettingsLayout from './SettingsLayout'

afterEach(() => {
  document.title = 'civex'
})

function at(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/settings" element={<SettingsLayout />}>
          <Route path="*" element={<p>section</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

describe('Settings tab titles', () => {
  it('say which area of Settings you are in', () => {
    at('/settings/appearance')
    expect(document.title).toBe('Appearance · Settings · civex')
  })

  it('say which tab of Storage too', () => {
    at('/settings/storage')
    expect(document.title).toBe('Volumes · Storage · Settings · civex')
  })

  it('follow the Storage tab in the address', () => {
    at('/settings/storage?tab=tasks')
    expect(document.title).toBe('Tasks · Storage · Settings · civex')
  })

  it('still follow the old tab addresses', () => {
    at('/settings/storage?tab=transfers')
    expect(document.title).toBe('Tasks · Storage · Settings · civex')
  })
})
