import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { ToastProvider } from '../components/ui/ToastProvider'
import { fakeServer } from '../components/files/testSupport'
import HealthPage from './HealthPage'

afterEach(() => vi.unstubAllGlobals())

const BROKEN = {
  ok: false,
  problems: [
    {
      kind: 'database',
      severity: 'fail',
      message: 'The database is stamped as up to date but lacks audit_log',
      fix: 'Repair adds what is missing, after backing the database up.',
      items: ['audit_log'],
    },
  ],
  checks: null,
  data_checked: false,
  can_repair: true,
  repair_offered: true,
}
const FINE = {
  ...BROKEN,
  ok: true,
  problems: [],
  data_checked: true,
  can_repair: false,
}

function show(routes: Record<string, unknown>) {
  const calls = fakeServer(routes as never)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter>
          <HealthPage />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
  return calls
}

describe('the Health page', () => {
  it('lists a problem in words and offers Repair', async () => {
    show({ '/api/health': BROKEN })
    expect(await screen.findByText(/lacks audit_log/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Repair' })).toBeInTheDocument()
  })

  it('offers no Repair when nothing is wrong', async () => {
    show({ '/api/health': FINE })
    expect(await screen.findByText('No problems found.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Repair' })).toBeNull()
  })

  it('repairs, then shows the new answer', async () => {
    show({
      '/api/health/repair': {
        backup: '/p/_civex/backups/x.db',
        added: ['audit_log'],
        health: FINE,
      },
      '/api/health': BROKEN,
    })
    fireEvent.click(await screen.findByRole('button', { name: 'Repair' }))
    expect(await screen.findByText('No problems found.')).toBeInTheDocument()
  })
})
