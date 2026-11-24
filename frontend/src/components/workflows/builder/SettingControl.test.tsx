import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { Schema } from '../../../api/schemas'
import type { Setting } from '../../../utils/pluginSettings'
import { SettingControl, type SettingContext } from './SettingControl'

const field = (id: string, name: string, label: string) => ({
  id,
  name,
  label,
  type: 'integer',
  required: false,
  restrictions: {},
  default: null,
  position: 0,
})

const SCHEMAS: Schema[] = [
  {
    id: 'p',
    name: 'recording',
    label: 'Recording',
    description: null,
    parent_id: null,
    display_template: null,
    fields: [field('f0', 'site', 'Site')],
    deleted_at: null,
  },
  {
    id: 's',
    name: 'selection',
    label: 'Selection',
    description: null,
    parent_id: 'p',
    display_template: null,
    fields: [
      field('f1', 'number', 'Number'),
      field('f2', 'channel', 'Channel'),
    ],
    deleted_at: null,
  },
]

const MATCH_ON: Setting = {
  key: 'match_on',
  title: 'Match rows by',
  description: '',
  type: 'array',
  required: false,
  default: undefined,
  hint: { kind: 'field', of: 'schema', many: true },
}

const ctx = (config: Record<string, unknown>): SettingContext => ({
  schema: 'recording',
  config,
  settings: [MATCH_ON],
  schemas: SCHEMAS,
  collections: [],
  takesFiles: false,
})

describe('a setting naming several fields', () => {
  it("offers a box per field of the kind's own, and ticks add to the list", async () => {
    const onChange = vi.fn()
    render(
      <QueryClientProvider client={new QueryClient()}>
        <SettingControl
          setting={MATCH_ON}
          value={['number']}
          onChange={onChange}
          onChangeSome={() => {}}
          ctx={ctx({ schema: 'selection' })}
        />
      </QueryClientProvider>,
    )

    expect(screen.getByRole('checkbox', { name: 'Number' })).toBeChecked()
    // A field of the record above isn't on a selection's own data.
    expect(screen.queryByRole('checkbox', { name: 'Site' })).toBeNull()

    await userEvent.click(screen.getByRole('checkbox', { name: 'Channel' }))
    expect(onChange).toHaveBeenCalledWith(['number', 'channel'])
  })
})
