import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FilterBuilder } from './FilterBuilder'
import {
  addChildById,
  emptyCondition,
  emptyGroup,
  type FilterGroupNode,
} from '../../utils/filterTree'
import type { FilterableField } from '../../utils/hierarchy'

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })

const field = (
  name: string,
  type: string,
  restrictions: Record<string, unknown> = {},
): FilterableField =>
  ({
    id: `f-${name}`,
    name,
    label: null,
    type,
    required: false,
    restrictions,
    default: null,
    position: 0,
    sourceSchemaName: 'visit',
    relation: 'self',
  }) as FilterableField

const FIELDS = [
  field('patient_ref', 'reference', { schema: 'patient' }),
  field('tags_ref', 'reference_list', { schema: 'patient' }),
  field('note', 'string'),
]

let searchCalls: URLSearchParams[]
beforeEach(() => {
  searchCalls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://x')
      if (url.pathname === '/api/records') {
        searchCalls.push(url.searchParams)
        return json([
          {
            id: 'abcdef12-0000-0000-0000-000000000000',
            dataset_id: 'd',
            schema_name: 'patient',
            parent_record_id: null,
            data: {},
            natural_name: 'Ada',
            created_at: '2026-01-01T00:00:00Z',
            updated_at: '2026-01-01T00:00:00Z',
            deleted_at: null,
            reference_labels: null,
          },
        ])
      }
      return json([])
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function Harness({ onRoot }: { onRoot: (r: FilterGroupNode) => void }) {
  const [root, setRoot] = useState<FilterGroupNode>(() => {
    const group = emptyGroup()
    return addChildById(group, group.id, emptyCondition())
  })
  return (
    <FilterBuilder
      root={root}
      fields={FIELDS}
      onChange={(r) => {
        setRoot(r)
        onRoot(r)
      }}
    />
  )
}

describe('FilterBuilder reference fields', () => {
  it('picks a record by name instead of asking for a UUID', async () => {
    const user = userEvent.setup()
    let latest: FilterGroupNode | null = null
    render(<Harness onRoot={(r) => (latest = r)} />)

    await user.selectOptions(
      screen.getByLabelText('Field'),
      'visit::patient_ref',
    )
    const input = await screen.findByPlaceholderText(/Search patient records/)
    await user.click(input)
    await user.click(await screen.findByText('Ada'))

    const cond = latest!.children[0] as {
      field: string
      op: string
      value: unknown
    }
    expect(cond).toMatchObject({
      field: 'patient_ref',
      op: 'eq',
      value: 'abcdef12-0000-0000-0000-000000000000',
    })
  })

  it('only offers a reference list a member test', async () => {
    const user = userEvent.setup()
    render(<Harness onRoot={() => {}} />)

    await user.selectOptions(screen.getByLabelText('Field'), 'visit::tags_ref')

    const ops = screen
      .getAllByRole('option')
      .map((o) => o.textContent)
      .filter((t) => t === 'includes' || t === 'is' || t === 'is any of')
    expect(ops).toEqual(['includes'])
  })
})
