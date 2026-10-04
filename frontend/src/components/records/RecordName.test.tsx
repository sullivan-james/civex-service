import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { RecordName } from './RecordName'
import { TargetLabel } from '../TargetLabel'
import { targetKeys } from '../../utils/pins'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const id = (n: number) =>
  `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`

let labelCalls: string[][]
let names: Record<string, { name: string | null; deleted?: boolean }>
let collections: { id: string; name: string }[]

beforeEach(() => {
  labelCalls = []
  names = {}
  collections = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      if (url.pathname === '/api/records/labels') {
        const { ids } = JSON.parse(String(init?.body)) as { ids: string[] }
        labelCalls.push(ids)
        return json(
          ids
            .filter((i) => i in names)
            .map((i) => ({
              id: i,
              schema_name: 'sel',
              natural_name: names[i].name,
              deleted: names[i].deleted ?? false,
            })),
        )
      }
      if (url.pathname === '/api/collections') return json(collections)
      return json({})
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function renderIt(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('RecordName', () => {
  it('shows the name as it is now, looked up from the id', async () => {
    names[id(1)] = { name: 'Selection 1' }
    renderIt(<RecordName id={id(1)} />)

    expect(await screen.findByText('Selection 1')).toBeInTheDocument()
  })

  it('looks up fifty names with one request, not fifty', async () => {
    const ids = Array.from({ length: 50 }, (_, i) => id(i + 1))
    ids.forEach((i, n) => (names[i] = { name: `Selection ${n + 1}` }))

    renderIt(
      <ul>
        {ids.map((i) => (
          <li key={i}>
            <RecordName id={i} />
          </li>
        ))}
      </ul>,
    )

    expect(await screen.findByText('Selection 50')).toBeInTheDocument()
    expect(screen.getByText('Selection 1')).toBeInTheDocument()
    expect(labelCalls).toHaveLength(1)
    expect(labelCalls[0]).toHaveLength(50)
  })

  it('asks once for a record that appears many times', async () => {
    names[id(1)] = { name: 'Selection 1' }
    renderIt(
      <>
        {[1, 2, 3].map((n) => (
          <span key={n}>
            <RecordName id={id(1)} />
          </span>
        ))}
      </>,
    )

    await waitFor(() =>
      expect(screen.getAllByText('Selection 1')).toHaveLength(3),
    )
    expect(labelCalls).toEqual([[id(1)]])
  })

  it('shows what it was given while loading, and when the record is gone', async () => {
    renderIt(<RecordName id={id(9)} fallback="the old name" />)

    expect(screen.getByText('the old name')).toBeInTheDocument()
    await waitFor(() => expect(labelCalls).toHaveLength(1))
    expect(screen.getByText('the old name')).toBeInTheDocument() // not found: kept
  })

  it('falls back to the start of the id when there is nothing else', async () => {
    renderIt(<RecordName id={id(9)} />)
    expect(screen.getByText(`${id(9).slice(0, 8)}…`)).toBeInTheDocument()
  })

  it('says when the record is in Recently Deleted', async () => {
    names[id(2)] = { name: 'Selection 2', deleted: true }
    renderIt(<RecordName id={id(2)} />)

    expect(await screen.findByText('(deleted)')).toBeInTheDocument()
    expect(screen.getByText(/Selection 2/)).toBeInTheDocument()
  })
})

describe('TargetLabel for pins and recents', () => {
  const record = (n: number, label: string) => ({
    key: targetKeys.record(id(n)),
    kind: 'record' as const,
    label,
    to: `/records/${id(n)}`,
  })

  it('names a pinned record as it is now, not as it was when pinned', async () => {
    names[id(3)] = { name: 'Selection 3 (renamed)' }
    renderIt(<TargetLabel target={record(3, 'Selection 3')} />)

    expect(screen.getByText('Selection 3')).toBeInTheDocument() // until known
    expect(await screen.findByText('Selection 3 (renamed)')).toBeInTheDocument()
  })

  it('names a pinned collection from the collection list, not as it was when pinned', async () => {
    collections = [{ id: 'c1', name: 'study (renamed)' }]
    renderIt(
      <TargetLabel
        target={{
          key: targetKeys.collection('c1'),
          kind: 'collection',
          label: 'study',
          to: '/collections/c1',
        }}
      />,
    )

    expect(await screen.findByText('study (renamed)')).toBeInTheDocument()
    expect(labelCalls).toEqual([]) // no record lookup for a collection
  })

  it('leaves everything else as pinned, and asks for nothing', async () => {
    renderIt(
      <TargetLabel
        target={{
          key: targetKeys.collection('c1'),
          kind: 'collection',
          label: 'study',
          to: '/collections/c1',
        }}
      />,
    )

    expect(screen.getByText('study')).toBeInTheDocument()
    await new Promise((r) => setTimeout(r, 30))
    expect(labelCalls).toEqual([])
  })
})
