import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { SyncServing } from './SyncServing'

let authority: { serving: boolean; devices: Record<string, unknown>[] }
let calls: { method: string; path: string; body: unknown }[]

function renderCard() {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), 'http://x').pathname
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      calls.push({ method: init?.method ?? 'GET', path, body })
      if (path === '/api/remote/authority' && init?.method === 'PATCH')
        authority = { ...authority, serving: body.serving }
      let answer: unknown = authority
      if (path === '/api/remote/authority/devices') {
        authority = {
          ...authority,
          devices: [
            {
              name: body.name,
              created_at: 'now',
              last_seen_at: null,
              revoked: false,
            },
          ],
        }
        answer = { ...authority, token: 'secret-token' }
      }
      return new Response(JSON.stringify(answer), {
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <SyncServing />
    </QueryClientProvider>,
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('SyncServing', () => {
  it('starts accepting devices, and issues a token shown once', async () => {
    authority = { serving: false, devices: [] }
    renderCard()
    await userEvent.click(
      await screen.findByRole('button', { name: 'Accept devices' }),
    )
    await userEvent.type(
      await screen.findByLabelText('New device'),
      'field laptop',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Issue a token' }))
    expect(await screen.findByText('secret-token')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('not shown again')
    await waitFor(() =>
      expect(
        calls.find((c) => c.path === '/api/remote/authority/devices')?.body,
      ).toEqual({ name: 'field laptop' }),
    )
  })

  it('revokes a device after asking', async () => {
    authority = {
      serving: true,
      devices: [
        { name: 'phone', created_at: 'x', last_seen_at: null, revoked: false },
      ],
    }
    renderCard()
    await userEvent.click(await screen.findByRole('button', { name: 'Revoke' }))
    const buttons = screen.getAllByRole('button', { name: 'Revoke' })
    await userEvent.click(buttons[buttons.length - 1])
    await waitFor(() =>
      expect(calls.map((c) => c.path)).toContain(
        '/api/remote/authority/devices/phone/revoke',
      ),
    )
  })
})
