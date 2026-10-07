import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { SyncServing } from './SyncServing'

let authority: {
  serving: boolean
  fingerprint: string | null
  devices: Record<string, unknown>[]
  invites: Record<string, unknown>[]
}
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
      if (path === '/api/remote/authority/invites') {
        authority = {
          ...authority,
          fingerprint: 'K7QM-29XD',
          invites: [
            { name: body.name, created_at: 'now', expires_at: 'later' },
          ],
        }
        answer = { ...authority, invite: 'civex_inv_secret' }
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
  it('starts accepting devices, and invites one with a code shown once', async () => {
    authority = { serving: false, fingerprint: null, devices: [], invites: [] }
    renderCard()
    await userEvent.click(
      await screen.findByRole('button', { name: 'Accept devices' }),
    )
    await userEvent.type(
      await screen.findByLabelText('New device'),
      'field laptop',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Invite' }))
    expect(await screen.findByText('civex_inv_secret')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('not shown again')
    expect(screen.getByText('K7QM-29XD')).toBeInTheDocument()
    await waitFor(() =>
      expect(
        calls.find((c) => c.path === '/api/remote/authority/invites')?.body,
      ).toEqual({ name: 'field laptop' }),
    )
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() =>
      expect(calls.map((c) => c.path)).toContain(
        '/api/remote/authority/invites/field%20laptop/cancel',
      ),
    )
  })

  it('revokes a device after asking', async () => {
    authority = {
      serving: true,
      fingerprint: 'K7QM-29XD',
      devices: [
        {
          name: 'phone',
          fingerprint: 'AB12-CD34',
          created_at: 'x',
          last_seen_at: null,
          revoked: false,
        },
      ],
      invites: [],
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
