import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router'
import { ToastProvider } from '../components/ui'
import { setFieldTypesForTest } from '../hooks/useFieldTypes'
import { schemasApi, type Schema } from '../api/schemas'
import SchemaDetailPage from './SchemaDetailPage'

const schema = {
  id: 's1',
  name: 'trial',
  label: null,
  description: null,
  parent_id: null,
  display_template: null,
  created_at: '2026-01-01T00:00:00Z',
  deleted_at: null,
  fields: [],
} as unknown as Schema

function renderPage(path = '/schemas/s1') {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <ToastProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/schemas/:id" element={<SchemaDetailPage />} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

describe('SchemaDetailPage', () => {
  beforeEach(() => {
    setFieldTypesForTest({ types: [], kinds: [] })
    vi.spyOn(schemasApi, 'get').mockResolvedValue(schema)
    vi.spyOn(schemasApi, 'list').mockResolvedValue([schema])
    vi.spyOn(schemasApi, 'getAudit').mockResolvedValue({
      items: [],
      total: 0,
    } as never)
    vi.spyOn(schemasApi, 'previewName').mockResolvedValue({
      name: null,
      error: null,
    })
  })

  it('shows the fields tab first, with no Browse records button', async () => {
    renderPage()
    expect(await screen.findByRole('tab', { name: 'Fields' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(screen.queryByRole('link', { name: /browse records/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /browse records/i })).toBeNull()
  })

  it('opens the tab named in the address', async () => {
    renderPage('/schemas/s1?tab=naming')
    expect(await screen.findByLabelText('Record name')).toBeInTheDocument()
  })

  it('keeps delete out of the way, in Settings', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByRole('tab', { name: 'Settings' })
    expect(screen.queryByRole('button', { name: 'Delete schema' })).toBeNull()
    await user.click(screen.getByRole('tab', { name: 'Settings' }))
    expect(
      screen.getByRole('button', { name: 'Delete schema' }),
    ).toBeInTheDocument()
  })
})
