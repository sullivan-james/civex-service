import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useState } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { schemasApi } from '../../api/schemas'
import { TemplateBuilder, type TemplateField } from './TemplateBuilder'

const FIELDS: TemplateField[] = [
  { name: 'site', label: 'Site', dtype: 'string' },
  { name: 'taken_on', label: 'Taken on', dtype: 'date' },
  { name: 'where', label: 'Where', dtype: 'geo' },
]

function Harness({ initial = '' }: { initial?: string }) {
  const [value, setValue] = useState(initial)
  return (
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <TemplateBuilder
        schemaName="trial"
        kind="record"
        value={value}
        onChange={setValue}
        fields={FIELDS}
        label="Record name"
      />
      <div data-testid="value">{value}</div>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  vi.spyOn(schemasApi, 'previewName').mockImplementation(async (_n, body) => ({
    name: body.template.includes('ghost') ? null : `rendered ${body.template}`,
    error: body.template.includes('ghost') ? 'unknown variable ghost' : null,
  }))
})

describe('TemplateBuilder', () => {
  it('adds a variable from a chip and leaves out types that cannot be named', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    expect(screen.queryByRole('button', { name: 'Where' })).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Site' }))
    expect(screen.getByTestId('value')).toHaveTextContent('{site}')
  })

  it('inserts at the cursor, not the end', async () => {
    const user = userEvent.setup()
    render(<Harness initial="a-b" />)
    const input = screen.getByLabelText('Record name') as HTMLInputElement
    input.focus()
    input.setSelectionRange(2, 2)
    await user.click(screen.getByRole('button', { name: 'Site' }))
    expect(screen.getByTestId('value')).toHaveTextContent('a-{site}b')
  })

  it('offers formats that suit the type and writes the choice into the template', async () => {
    const user = userEvent.setup()
    render(<Harness initial="{taken_on}" />)
    await user.selectOptions(
      screen.getByLabelText('Format for taken_on'),
      'YYYY-MM',
    )
    expect(screen.getByTestId('value')).toHaveTextContent('{taken_on:YYYY-MM}')
  })

  it('previews what the server renders and shows its error', async () => {
    const user = userEvent.setup()
    render(<Harness initial="{site}" />)
    expect(await screen.findByText('rendered {site}')).toBeInTheDocument()

    await user.type(screen.getByLabelText('Record name'), '{{ghost}')
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent(
        'unknown variable ghost',
      ),
    )
  })

  it('separates inherited fields and fields reached through a reference', async () => {
    const user = userEvent.setup()
    const fields: TemplateField[] = [
      { name: 'n', label: 'N', dtype: 'integer', source: null },
      { name: 'subject', label: 'Subject', dtype: 'string', source: 'Base' },
      {
        name: 'site',
        label: 'Site',
        dtype: 'reference',
        source: null,
        reach: [{ name: 'code', label: 'Code', dtype: 'string' }],
      },
    ]
    function Reach({ kind }: { kind: 'record' | 'file' }) {
      const [value, setValue] = useState('')
      return (
        <QueryClientProvider client={new QueryClient()}>
          <TemplateBuilder
            schemaName="trial"
            kind={kind}
            value={value}
            onChange={setValue}
            fields={fields}
            label="Name"
          />
          <div data-testid="value">{value}</div>
        </QueryClientProvider>
      )
    }
    const { unmount } = render(<Reach kind="record" />)
    expect(screen.getByText('This type')).toBeInTheDocument()
    expect(screen.getByText('From Base')).toBeInTheDocument()
    expect(screen.getByText('Via Site')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Code' }))
    expect(screen.getByTestId('value')).toHaveTextContent('{site.code}')
    unmount()

    // A file's name can use them too, and says its extension is its own.
    render(<Reach kind="file" />)
    expect(screen.getByText('Via Site')).toBeInTheDocument()
    expect(screen.getByText('.ext')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /ext/ })).toBeNull()
  })

  it('takes a value out with the separator beside it', async () => {
    const user = userEvent.setup()
    render(<Harness initial="{site}_{taken_on}" />)
    await user.click(screen.getByRole('button', { name: 'Remove Taken on' }))
    expect(screen.getByTestId('value')).toHaveTextContent(/^{site}$/)
  })

  it('lists many values in a searchable picker, grouped by where they come from', async () => {
    const user = userEvent.setup()
    const many: TemplateField[] = [
      ...Array.from({ length: 6 }, (_, i) => ({
        name: `f${i}`,
        label: `Field ${i}`,
        dtype: 'string',
      })),
      {
        name: 'species',
        label: 'Species',
        dtype: 'reference',
        source: 'Encounter',
        reach: [{ name: 'common', label: 'Common name', dtype: 'string' }],
      },
      { name: 'site', label: 'Site', dtype: 'string', source: 'Encounter' },
    ]
    function Many() {
      const [value, setValue] = useState('{f0}_')
      return (
        <QueryClientProvider client={new QueryClient()}>
          <TemplateBuilder
            schemaName="selection"
            kind="file"
            value={value}
            onChange={setValue}
            fields={many}
            label="Download name"
          />
          <div data-testid="value">{value}</div>
        </QueryClientProvider>
      )
    }
    render(<Many />)
    expect(screen.queryByRole('button', { name: 'Field 1' })).toBeNull()

    await user.click(screen.getByRole('button', { name: 'Insert a value' }))
    expect(
      screen.getByRole('group', { name: 'Via Species (Encounter)' }),
    ).toBeInTheDocument()
    await user.type(screen.getByLabelText('Search values'), 'common')
    expect(screen.queryByRole('group', { name: 'This type' })).toBeNull()
    await user.keyboard('{Enter}')

    expect(screen.getByTestId('value')).toHaveTextContent(
      '{f0}_{species.common}',
    )
    expect(screen.getByText('Species › Common name')).toBeInTheDocument()
  })
})
