import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ToastProvider } from '../ui'
import { schemasApi, type Schema } from '../../api/schemas'
import { fieldsWithInherited } from '../../utils/schemaFields'
import { NamingSection } from './NamingSection'

const field = (name: string, type = 'string') =>
  ({
    id: name,
    name,
    label: null,
    type,
    required: false,
    restrictions: {},
  }) as never

const parent = {
  id: 'p',
  name: 'base',
  label: null,
  parent_id: null,
  display_template: null,
  fields: [field('subject'), field('site')],
} as unknown as Schema
const child = {
  id: 'c',
  name: 'child',
  label: null,
  parent_id: 'p',
  display_template: null,
  fields: [field('site', 'integer'), field('depth', 'float')],
} as unknown as Schema

describe('fieldsWithInherited', () => {
  it('lists own fields first and lets an own field hide an inherited one', () => {
    const got = fieldsWithInherited(child, [parent, child])
    expect(got.map((f) => [f.name, f.dtype])).toEqual([
      ['site', 'integer'],
      ['depth', 'float'],
      ['subject', 'string'],
    ])
  })
})

describe('NamingSection', () => {
  beforeEach(() => {
    vi.spyOn(schemasApi, 'previewName').mockResolvedValue({
      name: 'x',
      error: null,
    })
  })

  it('saves the template it was edited to', async () => {
    const update = vi
      .spyOn(schemasApi, 'update')
      .mockResolvedValue({ ...child, display_template: '{subject}' })
    const user = userEvent.setup()
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ToastProvider>
          <NamingSection schema={child} allSchemas={[parent, child]} />
        </ToastProvider>
      </QueryClientProvider>,
    )
    const save = screen.getByRole('button', { name: 'Save' })
    expect(save).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Subject' }))
    await user.click(save)
    await waitFor(() =>
      expect(update).toHaveBeenCalledWith('child', {
        display_template: '{subject}',
      }),
    )
  })
})
