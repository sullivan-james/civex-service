import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { AuditEvent } from '../../api/audit'
import { EarlierActivity } from './EarlierActivity'

let earlier: boolean
vi.mock('../../hooks/useRemote', () => ({
  useRemoteStatus: () => ({ data: { earlier_history: earlier } }),
}))

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })

const event = (id: string): AuditEvent => ({
  id,
  kind: 'entry',
  timestamp: '2026-01-01T12:00:00Z',
  count: 1,
  entry: {
    id,
    action: 'create',
    entity_type: 'dataset',
    entity_id: 'd1',
    old_data: null,
    new_data: { name: id },
    timestamp: '2026-01-01T12:00:00Z',
    changes: [],
    now: null,
  },
  batch: null,
  parts: [],
})

let urls: string[]
let replies: unknown[]

beforeEach(() => {
  earlier = true
  urls = []
  replies = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      urls.push(String(input))
      return json(replies.shift())
    }),
  )
})

function renderIt(under?: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <EarlierActivity under={under} />
    </QueryClientProvider>,
  )
}

describe('EarlierActivity', () => {
  it('reads nothing until asked, then a page at a time', async () => {
    replies = [
      { items: [event('one')], next_before: 7, offline: false },
      { items: [event('two')], next_before: null, offline: false },
    ]
    renderIt('r1')
    expect(urls).toEqual([])
    await userEvent.click(screen.getByText('Show earlier activity'))
    await waitFor(() => expect(screen.getByText('Show more')).toBeTruthy())
    expect(urls[0]).toContain('/audit/earlier?')
    expect(urls[0]).toContain('under=r1')
    expect(urls[0]).not.toContain('before=')
    await userEvent.click(screen.getByText('Show more'))
    await waitFor(() => expect(urls[1]).toContain('before=7'))
    await waitFor(() => expect(screen.queryByText('Show more')).toBeNull())
  })

  it('says where the rest is when the server cannot be reached', async () => {
    replies = [{ items: [], next_before: null, offline: true }]
    renderIt()
    await userEvent.click(screen.getByText('Show earlier activity'))
    await waitFor(() =>
      expect(
        screen.getByText(/Earlier activity is on the server\./),
      ).toBeTruthy(),
    )
  })

  it('shows nothing for a project with no earlier history', () => {
    earlier = false
    const { container } = renderIt()
    expect(container.textContent).toBe('')
  })
})
