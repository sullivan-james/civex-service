import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { FieldIndex } from '../../api/indexes'
import { FieldIndexRow } from './FieldIndexRow'

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

const state = (over: Partial<FieldIndex> = {}): FieldIndex => ({
  field_id: 'f1',
  field: 'depth',
  schema_name: 'sample',
  indexed: false,
  reasons: [],
  built: false,
  indexable: true,
  ...over,
})

let current: FieldIndex
let puts: unknown[]
beforeEach(() => {
  puts = []
  current = state()
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      if (!url.pathname.endsWith('/fields/depth/index')) return json({}, 404)
      if (init?.method === 'PUT') {
        const body = JSON.parse(String(init.body))
        puts.push(body)
        current = state({
          indexed: body.indexed,
          reasons: body.indexed ? ['chosen'] : [],
        })
      }
      return json(current)
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function renderRow() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <FieldIndexRow schemaName="sample" fieldName="depth" />
    </QueryClientProvider>,
  )
}

describe('FieldIndexRow', () => {
  it('asks for an index at once and says it is being built', async () => {
    renderRow()
    const box = await screen.findByRole('checkbox', { name: /Indexed/ })
    expect(box).not.toBeChecked()
    await userEvent.click(box)
    await waitFor(() => expect(puts).toEqual([{ indexed: true }]))
    expect(
      await screen.findByRole('checkbox', { name: /building/ }),
    ).toBeChecked()
  })

  it('is on and locked for a field in a uniqueness key', async () => {
    current = state({ indexed: true, built: true, reasons: ['unique_key'] })
    renderRow()
    const box = await screen.findByRole('checkbox', { name: 'Indexed' })
    expect(box).toBeChecked()
    expect(box).toBeDisabled()
  })

  it('is not offered for a field that cannot be indexed', async () => {
    current = state({ indexable: false })
    const { container } = renderRow()
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
  })
})
