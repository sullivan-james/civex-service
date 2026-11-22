import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { ToastProvider } from '../ui/ToastProvider'
import { setFieldTypesForTest } from '../../hooks/useFieldTypes'
import type { Schema } from '../../api/schemas'
import { KindCharts } from './KindCharts'

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    headers: { 'Content-Type': 'application/json' },
  })

const sample = (charts: Schema['charts']): Schema => ({
  id: 's1',
  name: 'sample',
  label: null,
  description: null,
  parent_id: null,
  display_template: null,
  deleted_at: null,
  charts,
  fields: [
    {
      id: 'f1',
      name: 'site',
      label: null,
      type: 'string',
      required: false,
      restrictions: {},
      default: null,
      position: 0,
    },
  ],
})

let put: unknown[] | null
beforeEach(() => {
  put = null
  setFieldTypesForTest({
    types: [
      {
        type: 'string',
        label: 'Text',
        description: '',
        stored_as: '',
        entry_hint: '',
        example: '',
        restrictions: [],
        supports_default: true,
        searchable: true,
        measures: ['filled', 'distinct', 'min', 'max'],
        grouping: 'value',
        buckets: [],
      },
    ],
    kinds: [],
    summary_measures: [],
  })
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      if (url.pathname === '/api/schemas/sample/charts') {
        put = JSON.parse(String(init!.body)).charts
        return json(sample(put as Schema['charts']))
      }
      if (url.pathname === '/api/records/summary') {
        const body = JSON.parse(String(init!.body))
        const grouped = body.group_by.length > 0
        return json({
          schema_name: 'sample',
          group_columns: grouped
            ? [
                {
                  key: 'site',
                  field: 'site',
                  schema_name: 'sample',
                  label: 'Site',
                  type: 'string',
                  bucket: null,
                  bin: null,
                  unit: null,
                },
              ]
            : [],
          measure_columns: body.measures.map((key: string) => ({
            key,
            measure: key.split(':')[0],
            label: key,
            field: null,
            schema_name: null,
            type: null,
            unit: null,
          })),
          rows: [],
          total: body.measures.map(() => 3),
          truncated: false,
          limit: 1000,
          timezone: null,
        })
      }
      return json({})
    }),
  )
})
afterEach(() => {
  vi.unstubAllGlobals()
  setFieldTypesForTest(null)
})

function show(schema: Schema) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <MemoryRouter>
          <KindCharts schema={schema} schemas={[schema]} />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

describe('a kind’s charts', () => {
  it('has no charts until someone adds one, and saves the one added', async () => {
    show(sample([]))
    expect(screen.queryByText(/How many samples/)).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: /Add chart/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Add chart' }))
    await waitFor(() =>
      expect(put).toEqual([
        expect.objectContaining({ group_by: ['site'], measures: ['count'] }),
      ]),
    )
  })

  it('shows the charts that are set, as they are', async () => {
    show(
      sample([
        { id: 'a', title: 'By site', group_by: ['site'], measures: ['count'] },
      ]),
    )
    expect(await screen.findByText('By site')).toBeInTheDocument()
  })
})
