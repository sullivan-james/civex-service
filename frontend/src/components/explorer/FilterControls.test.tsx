import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { FilterControls } from './FilterControls'
import type { FilterTreeWire } from '../../utils/filterTree'
import type { FilterableField } from '../../utils/hierarchy'

const ADA = 'abcdef12-0000-0000-0000-000000000000'
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
  field('note', 'string'),
  field('age', 'integer'),
]

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://x')
      if (url.pathname === `/api/records/${ADA}`)
        return json({
          id: ADA,
          dataset_id: 'd',
          schema_name: 'patient',
          parent_record_id: null,
          data: {},
          natural_name: 'Ada',
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
          deleted_at: null,
          reference_labels: null,
        })
      return json([])
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function renderControls(
  wire: FilterTreeWire | null,
  onChange: (w: FilterTreeWire | null) => void = () => {},
) {
  const ui = (w: FilterTreeWire | null) => (
    <QueryClientProvider client={client}>
      <FilterControls
        wire={w}
        fields={FIELDS}
        listedSchema="visit"
        onChange={onChange}
      />
    </QueryClientProvider>
  )
  const client = new QueryClient()
  const view = render(ui(wire))
  return { rerender: (w: FilterTreeWire | null) => view.rerender(ui(w)) }
}

describe('FilterControls', () => {
  it('names a referenced record in its chip instead of showing the id', async () => {
    renderControls({ field: 'patient_ref', op: 'eq', value: ADA })

    expect(await screen.findByText('Patient Ref is Ada')).toBeInTheDocument()
    expect(screen.queryByText(new RegExp(ADA))).not.toBeInTheDocument()
  })

  it('shows the short id until the name arrives, never the full UUID', () => {
    renderControls({ field: 'patient_ref', op: 'eq', value: ADA })

    expect(screen.getByText(/Patient Ref is abcdef12/)).toBeInTheDocument()
  })

  it('opens the editor in the page, not as a floating dialog', async () => {
    const user = userEvent.setup()
    renderControls({ field: 'note', op: 'eq', value: 'x' })

    await user.click(screen.getByRole('button', { name: /Filter/ }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    const editor = screen.getByRole('region', { name: 'Edit filters' })
    expect(editor).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Done' })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
  })

  it('starts a blank condition when there is no filter yet', async () => {
    const user = userEvent.setup()
    renderControls(null)

    await user.click(screen.getByRole('button', { name: /Filter/ }))

    expect(screen.getByLabelText('Field')).toBeInTheDocument()
  })

  it('sends numbers as numbers, so the server compares them numerically', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    renderControls(null, onChange)
    await user.click(screen.getByRole('button', { name: /Filter/ }))

    await user.selectOptions(screen.getByLabelText('Field'), 'visit::age')
    await user.type(screen.getByRole('spinbutton'), '30')

    expect(onChange).toHaveBeenLastCalledWith({
      and: [{ field: 'age', op: 'eq', value: 30, schema: 'visit' }],
    })
  })

  it('follows a filter changed from outside while open', async () => {
    const user = userEvent.setup()
    const { rerender } = renderControls({ field: 'note', op: 'eq', value: 'x' })
    await user.click(screen.getByRole('button', { name: /Filter/ }))
    expect(screen.getByRole('textbox', { name: 'Value' })).toHaveValue('x')

    rerender({ field: 'note', op: 'eq', value: 'y' })

    expect(screen.getByRole('textbox', { name: 'Value' })).toHaveValue('y')
  })

  it('keeps a half-typed edit while the page echoes the change back', async () => {
    const user = userEvent.setup()
    let current: FilterTreeWire | null = { field: 'note', op: 'eq', value: '' }
    const onChange = vi.fn((w: FilterTreeWire | null) => (current = w))
    const { rerender } = renderControls(current, onChange)
    await user.click(screen.getByRole('button', { name: /Filter/ }))

    await user.type(screen.getByRole('textbox', { name: 'Value' }), 'ab')
    rerender(current)

    expect(screen.getByRole('textbox', { name: 'Value' })).toHaveValue('ab')
  })
})
