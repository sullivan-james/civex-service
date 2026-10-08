import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import type { UpdateStatus } from '../../api/updates'
import { restartForUpdate } from '../../utils/updateRestart'
import { useUpdateTasks } from './useUpdateTasks'

const upToDate: UpdateStatus = {
  current: '1.2.0',
  latest: '1.2.0',
  newer: false,
  pre: false,
  installer: 'uv',
  can_update: true,
  blocked: '',
  error: '',
  last: null,
  running: [],
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function tasksFor(
  status: UpdateStatus,
  fetchMock = vi.fn(),
  answer?: (url: string, init?: RequestInit) => Promise<Response>,
) {
  fetchMock.mockImplementation(
    answer ??
      (async (url: string) =>
        url.startsWith('/api/update') ? json(status) : json({})),
  )
  vi.stubGlobal('fetch', fetchMock)
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  )
  return renderHook(() => useUpdateTasks(), { wrapper })
}

beforeEach(() => localStorage.clear())
afterEach(() => vi.unstubAllGlobals())

describe('useUpdateTasks', () => {
  it('is quiet when civex is up to date', async () => {
    const { result } = tasksFor(upToDate)
    await new Promise((r) => setTimeout(r, 20))
    expect(result.current).toEqual([])
  })

  it('offers a newer version until it is put off for that version', async () => {
    const { result } = tasksFor({ ...upToDate, latest: '1.3.0', newer: true })
    await waitFor(() => expect(result.current).toHaveLength(1))
    expect(result.current[0]).toMatchObject({
      title: 'civex 1.3.0 is available',
      note: 'You have 1.2.0',
    })
    const later = result.current[0].actions?.find((a) => a.label === 'Later')
    act(() => later?.onClick?.())
    expect(result.current).toEqual([])
  })

  it('does not offer what this copy cannot install', async () => {
    const { result } = tasksFor({
      ...upToDate,
      latest: '1.3.0',
      newer: true,
      can_update: false,
      blocked: 'This is a development (editable) install.',
    })
    await new Promise((r) => setTimeout(r, 20))
    expect(result.current).toEqual([])
  })

  it('says the last update did not work until it is dismissed, for good', async () => {
    let dismissed = false
    const deletes: string[] = []
    const { result } = tasksFor(upToDate, vi.fn(), async (url, init) => {
      if (init?.method === 'DELETE') {
        deletes.push(url)
        dismissed = true
        return new Response(null, { status: 204 })
      }
      return json({
        ...upToDate,
        last: dismissed
          ? null
          : {
              at: '2026-10-07T10:00:00Z',
              from_version: '1.2.0',
              to_version: '1.2.0',
              ok: false,
              message: 'The upgrade failed (exit 1).',
            },
      })
    })
    await waitFor(() => expect(result.current).toHaveLength(1))
    expect(result.current[0]).toMatchObject({
      tone: 'attention',
      detail: 'The upgrade failed (exit 1).',
    })
    const dismiss = result.current[0].actions?.find(
      (a) => a.label === 'Dismiss',
    )
    act(() => dismiss?.onClick?.())
    // Forgotten by the server, so it stays gone in the next window too.
    await waitFor(() => expect(result.current).toEqual([]))
    expect(deletes).toEqual(['/api/update/last'])
  })

  it('sends a newer version with others running to the Updates page', async () => {
    const { result } = tasksFor({
      ...upToDate,
      latest: '1.3.0',
      newer: true,
      running: ['civex serve --port 8100 (in C:\\p)'],
    })
    await waitFor(() => expect(result.current).toHaveLength(1))
    expect(result.current[0].actions?.[0]).toMatchObject({
      label: 'Update…',
      to: '/settings/updates',
    })
  })

  it('says why when civex refuses to start the update', async () => {
    const fetchMock = vi.fn()
    const { result } = tasksFor(upToDate, fetchMock)
    fetchMock.mockImplementation(async () =>
      json({ detail: 'This server is open to other computers.' }, 409),
    )
    await act(() => restartForUpdate({ pre: false }))
    expect(result.current[0]).toMatchObject({
      tone: 'attention',
      title: 'civex couldn’t start the update',
      detail: 'This server is open to other computers.',
    })
    const dismiss = result.current[0].actions?.find(
      (a) => a.label === 'Dismiss',
    )
    act(() => dismiss?.onClick?.())
    await waitFor(() => expect(result.current).toEqual([]))
  })
})
