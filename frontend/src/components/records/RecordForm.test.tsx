import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RecordForm } from './RecordForm'
import type { Field, Schema } from '../../api/schemas'

function field(name: string, type: string, extra: Partial<Field> = {}): Field {
  return {
    id: `id-${name}`,
    name,
    label: null,
    type,
    required: false,
    restrictions: {},
    default: null,
    position: 0,
    ...extra,
  }
}

function schema(name: string, fields: Field[]): Schema {
  return {
    id: `s-${name}`,
    name,
    label: null,
    description: null,
    parent_id: null,
    display_fields: [],
    fields,
    deleted_at: null,
  }
}

function renderForm(props: Partial<React.ComponentProps<typeof RecordForm>>) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <RecordForm
        schemas={[]}
        datasetName="ds"
        onSubmit={() => {}}
        onCancel={() => {}}
        {...props}
      />
    </QueryClientProvider>,
  )
}

describe('RecordForm', () => {
  const sample = schema('sample', [
    field('count', 'integer'),
    field('ratio', 'float'),
    field('note', 'string'),
  ])

  it('coerces numeric inputs and omits empty fields on submit', async () => {
    const onSubmit = vi.fn()
    renderForm({ schemas: [sample], onSubmit })
    const [count, ratio] = screen.getAllByRole('spinbutton')
    fireEvent.change(count, { target: { value: '7' } })
    fireEvent.change(ratio, { target: { value: '2.5' } })
    await userEvent.click(
      screen.getByRole('button', { name: /create|save|add/i }),
    )
    expect(onSubmit).toHaveBeenCalledWith(
      'sample',
      { count: 7, ratio: 2.5 },
      undefined,
    )
  })

  it('calls onCancel', async () => {
    const onCancel = vi.fn()
    renderForm({ schemas: [sample], onCancel })
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onCancel).toHaveBeenCalled()
  })

  it('switching schema resets entered values', async () => {
    const other = schema('other', [field('count', 'integer')])
    const onSubmit = vi.fn()
    renderForm({ schemas: [sample, other], onSubmit })
    fireEvent.change(screen.getAllByRole('spinbutton')[0], {
      target: { value: '4' },
    })
    await userEvent.click(screen.getByRole('button', { name: 'other' }))
    await userEvent.click(screen.getByRole('button', { name: 'sample' }))
    expect(screen.getAllByRole('spinbutton')[0]).toHaveValue(null)
  })

  it('renders nothing when no schema is selectable', () => {
    const { container } = renderForm({ schemas: [] })
    expect(container).toBeEmptyDOMElement()
  })
})
