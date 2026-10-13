import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { ToastProvider } from '../../ui/ToastProvider'
import StorageSettings from './StorageSettings'
import { TasksTab } from './TasksTab'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const status = (over: Record<string, unknown> = {}) => ({
  bucket: null,
  prefix: '',
  region: null,
  endpoint: null,
  profile: null,
  direct: true,
  bucket_files: 0,
  bucket_bytes: 0,
  drive_files: 0,
  drive_bytes: 0,
  left_on_drives: 0,
  can_switch: true,
  blocked: null,
  ...over,
})

type Call = { method: string; path: string; body?: unknown }
let calls: Call[]
let features: string[]
let bucket: ReturnType<typeof status>

beforeEach(() => {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      const method = init?.method ?? 'GET'
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      calls.push({ method, path: url.pathname, body })
      const p = url.pathname
      if (p === '/api/status/features') return json({ features, all: {} })
      if (p === '/api/store/bucket' && method === 'GET') return json(bucket)
      if (p === '/api/store/bucket/check')
        return json({
          ok: true,
          problems: [],
          warnings: ['The endpoint is plain http://'],
        })
      if (p === '/api/store/bucket' && method === 'PUT') {
        bucket = status({ bucket: body.bucket, endpoint: body.endpoint })
        return json(bucket)
      }
      if (p === '/api/store/volumes' || p === '/api/store/transfers')
        return json([])
      return json([])
    }),
  )
})

afterEach(() => vi.unstubAllGlobals())

function show(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter>{ui}</MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

describe('a project keeping its files in a bucket', () => {
  it('shows the bucket instead of drives, and can’t go back while it holds files', async () => {
    features = ['store_admin', 'direct_files']
    bucket = status({
      bucket: 'lab',
      prefix: 'humpbacks',
      endpoint: 'http://127.0.0.1:9000',
      bucket_files: 3,
      bucket_bytes: 2048,
      can_switch: false,
      blocked: 'This project keeps 3 files in the bucket.',
    })
    show(<StorageSettings />)

    expect(await screen.findByText('lab/humpbacks')).toBeInTheDocument()
    expect(screen.getByText('http://127.0.0.1:9000')).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'Volumes' })).toBeNull()
    const drives = screen.getByRole('button', { name: 'Use drives…' })
    expect(drives).toBeDisabled()
    expect(drives).toHaveAttribute(
      'title',
      'This project keeps 3 files in the bucket.',
    )
  })
})

describe('a project on drives', () => {
  it('tries a bucket, then uses it', async () => {
    features = ['volumes', 'store_admin']
    bucket = status()
    show(<TasksTab />)

    const user = userEvent.setup()
    const start = await screen.findByRole('button', { name: 'Use a bucket…' })
    await waitFor(() => expect(start).toBeEnabled())
    await user.click(start)
    await user.type(screen.getByLabelText(/Bucket/), 'lab')
    await user.type(screen.getByLabelText(/Endpoint/), 'http://127.0.0.1:9000')
    await user.click(screen.getByRole('button', { name: 'Check' }))
    expect(
      await screen.findByText('The endpoint is plain http://'),
    ).toBeInTheDocument()
    expect(screen.getByText('The bucket can be used.')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Use this bucket' }))
    await waitFor(() =>
      expect(
        calls.find((c) => c.method === 'PUT' && c.path === '/api/store/bucket')
          ?.body,
      ).toMatchObject({ bucket: 'lab', endpoint: 'http://127.0.0.1:9000' }),
    )
  })

  it('can’t start using a bucket while files are on drives, and says why', async () => {
    features = ['volumes', 'store_admin']
    bucket = status({
      drive_files: 5,
      can_switch: false,
      blocked: 'This project keeps 5 files on its drives.',
    })
    show(<TasksTab />)
    const start = await screen.findByRole('button', { name: 'Use a bucket…' })
    await waitFor(() =>
      expect(start).toHaveAttribute(
        'title',
        'This project keeps 5 files on its drives.',
      ),
    )
    expect(start).toBeDisabled()
  })
})
