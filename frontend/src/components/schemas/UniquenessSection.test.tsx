import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ToastProvider } from '../ui'
import { schemasApi, type Schema } from '../../api/schemas'
import { UniquenessSection } from './UniquenessSection'

const field = (name: string, type = 'string') =>
  ({
    id: name,
    name,
    label: null,
    type,
    required: false,
    restrictions: {},
  }) as never

const plot = {
  id: 'p',
  name: 'plot',
  label: null,
  parent_id: null,
  display_template: null,
  unique_keys: [['site', 'number']],
  fields: [field('site'), field('number', 'integer'), field('photo', 'file')],
} as unknown as Schema

function renderSection(schema: Schema = plot) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <UniquenessSection schema={schema} />
      </ToastProvider>
    </QueryClientProvider>,
  )
}

describe('UniquenessSection', () => {
  it('lists the rules and offers only fields that can be unique', () => {
    renderSection()
    expect(screen.getByText('Site + Number')).toBeInTheDocument()
    expect(screen.getByLabelText('Site')).toBeInTheDocument()
    expect(screen.queryByLabelText('Photo')).toBeNull()
  })

  it('adds a rule from the ticked fields, in schema order', async () => {
    const set = vi
      .spyOn(schemasApi, 'setUniqueKeys')
      .mockResolvedValue({ ...plot })
    const user = userEvent.setup()
    renderSection({ ...plot, unique_keys: [] })
    await user.click(screen.getByLabelText('Number'))
    await user.click(screen.getByLabelText('Site'))
    await user.click(screen.getByRole('button', { name: 'Add rule' }))
    await waitFor(() =>
      expect(set).toHaveBeenCalledWith('plot', [['site', 'number']]),
    )
  })

  it('removes a rule', async () => {
    const set = vi
      .spyOn(schemasApi, 'setUniqueKeys')
      .mockResolvedValue({ ...plot, unique_keys: [] })
    const user = userEvent.setup()
    renderSection()
    await user.click(
      screen.getByRole('button', { name: /Remove the rule Site \+ Number/ }),
    )
    await waitFor(() => expect(set).toHaveBeenCalledWith('plot', []))
  })

  it('shows the server’s reason when a rule is refused', async () => {
    vi.spyOn(schemasApi, 'setUniqueKeys').mockRejectedValue(
      new Error('2 sets of existing records already share those values'),
    )
    const user = userEvent.setup()
    renderSection({ ...plot, unique_keys: [] })
    await user.click(screen.getByLabelText('Site'))
    await user.click(screen.getByRole('button', { name: 'Add rule' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      /already share those values/,
    )
  })
})
