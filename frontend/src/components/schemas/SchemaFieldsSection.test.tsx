import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { ToastProvider } from '../ui'
import { setFieldTypesForTest } from '../../hooks/useFieldTypes'
import type { FieldTypes, Schema } from '../../api/schemas'
import { SchemaFieldsSection } from './SchemaFieldsSection'

const R = (key: string, label: string, control: string) => ({
  key,
  label,
  control,
  help: '',
})
const DESCRIPTORS: FieldTypes = {
  types: [
    {
      type: 'string',
      label: 'Text',
      description: 'Free text.',
      stored_as: 'Text',
      entry_hint: '',
      example: '',
      restrictions: [R('choices', 'Allowed values', 'choices')],
      supports_default: true,
    },
    {
      type: 'float',
      label: 'Decimal number',
      description: 'Measurements.',
      stored_as: 'Decimal number',
      entry_hint: '',
      example: '',
      restrictions: [
        R('min', 'Smallest allowed', 'number'),
        R('unit', 'Unit', 'unit'),
      ],
      supports_default: true,
    },
    {
      type: 'geo',
      label: 'Location',
      description: 'A point, line or area.',
      stored_as: 'GeoJSON',
      entry_hint: '',
      example: '',
      restrictions: [
        R('geometry_types', 'Shapes allowed', 'geometry_types'),
        R('bbox', 'Restrict to an area', 'bbox'),
      ],
      supports_default: false,
    },
  ],
  kinds: [
    {
      key: 'text',
      label: 'Text',
      type: 'string',
      description: 'Free text.',
      focus: null,
    },
    {
      key: 'quantity',
      label: 'Quantity',
      type: 'float',
      description: 'With a unit.',
      focus: 'unit',
    },
    {
      key: 'location',
      label: 'Location',
      type: 'geo',
      description: 'Where.',
      focus: 'geometry_types',
    },
  ],
}

const field = (id: string, name: string, type: string, restrictions = {}) => ({
  id,
  name,
  label: null,
  type,
  required: false,
  restrictions,
  default: null,
  position: 0,
})
const SCHEMA: Schema = {
  id: 's1',
  name: 'deployment',
  label: null,
  description: null,
  parent_id: null,
  display_fields: [],
  deleted_at: null,
  fields: [
    field('f1', 'species', 'string'),
    field('f2', 'depth', 'float', { unit: 'm' }),
  ],
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })

let calls: { method: string; path: string; body: unknown }[]
beforeEach(() => {
  calls = []
  setFieldTypesForTest(DESCRIPTORS)
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), 'http://x')
      const method = init?.method ?? 'GET'
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      if (method !== 'GET') calls.push({ method, path: url.pathname, body })
      if (method === 'POST' && url.pathname.endsWith('/fields'))
        return json(
          { ...field('new', body.name, body.type, body.restrictions ?? {}) },
          201,
        )
      if (method === 'PATCH')
        return json(field('f2', 'depth', 'float', body.restrictions ?? {}))
      return json([SCHEMA])
    }),
  )
})
afterEach(() => {
  setFieldTypesForTest(null)
  vi.unstubAllGlobals()
})

function renderSection() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter>
          <SchemaFieldsSection schema={SCHEMA} allSchemas={[SCHEMA]} />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

describe('schema fields section', () => {
  it('lists fields on the left and shows the selected one on the right', async () => {
    renderSection()
    const nav = screen.getByRole('navigation', { name: 'Fields' })
    expect(within(nav).getByText('Species')).toBeInTheDocument()
    expect(within(nav).getByText('Depth')).toBeInTheDocument()
    // the first field is open, with its rules
    expect(screen.getByRole('heading', { name: 'Species' })).toBeInTheDocument()
    expect(screen.getByText('Allowed values')).toBeInTheDocument()

    await userEvent.click(within(nav).getByText('Depth'))
    expect(screen.getByRole('heading', { name: 'Depth' })).toBeInTheDocument()
    expect(screen.getByLabelText('Unit')).toHaveValue('m')
  })

  it('starts a new field from the kind of data and saves its rules', async () => {
    renderSection()
    await userEvent.click(screen.getByRole('button', { name: '+ Add field' }))
    await userEvent.click(screen.getByRole('button', { name: /Location/ }))
    // the kind's lead rule comes first
    expect(screen.getByText('Shapes allowed')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Field label'), 'Release point')
    await userEvent.click(screen.getByLabelText('Point'))
    await userEvent.click(screen.getByRole('button', { name: 'Add field' }))
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].path).toBe('/api/schemas/deployment/fields')
    expect(calls[0].body).toMatchObject({
      name: 'release_point',
      type: 'geo',
      restrictions: { geometry_types: ['Point'] },
    })
  })

  it('saves a changed rule on an existing field', async () => {
    renderSection()
    await userEvent.click(
      within(screen.getByRole('navigation', { name: 'Fields' })).getByText(
        'Depth',
      ),
    )
    const save = screen.getByRole('button', { name: 'Save changes' })
    expect(save).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Smallest allowed'), '0')
    await userEvent.click(save)
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]).toMatchObject({
      method: 'PATCH',
      path: '/api/schemas/deployment/fields/depth',
      body: { restrictions: { unit: 'm', min: 0 } },
    })
  })

  it('asks before throwing away unsaved edits', async () => {
    renderSection()
    const nav = screen.getByRole('navigation', { name: 'Fields' })
    await userEvent.type(screen.getByLabelText('Field label'), 'x')
    await userEvent.click(within(nav).getByText('Depth'))
    expect(screen.getByText('Discard unsaved changes?')).toBeInTheDocument()
    await userEvent.click(
      within(screen.getByRole('dialog')).getByRole('button', {
        name: 'Cancel',
      }),
    )
    expect(screen.getByRole('heading', { name: 'Species' })).toBeInTheDocument()
    await userEvent.click(within(nav).getByText('Depth'))
    await userEvent.click(
      within(screen.getByRole('dialog')).getByRole('button', {
        name: 'Discard changes',
      }),
    )
    expect(screen.getByRole('heading', { name: 'Depth' })).toBeInTheDocument()
  })
})
