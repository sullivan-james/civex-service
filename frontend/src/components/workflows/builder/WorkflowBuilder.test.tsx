import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { useState } from 'react'
import type { PluginInfo } from '../../../api/plugins'
import type { Schema } from '../../../api/schemas'
import { emptyDraft, type WorkflowDraft } from '../../../utils/workflowModel'
import { WorkflowBuilder } from './WorkflowBuilder'

const plugin = (over: Partial<PluginInfo>): PluginInfo => ({
  id: 'x',
  name: 'X',
  description: '',
  builtin: true,
  category: 'data-sources',
  capabilities: [],
  inputs: [],
  outputs: [],
  config_schema: { properties: {} },
  filename: null,
  ...over,
})

const PLUGINS: PluginInfo[] = [
  plugin({
    id: 'civex.load_file',
    name: 'Read a file',
    outputs: [
      {
        name: 'bytes',
        type: 'bytes',
        required: true,
        description: 'The file’s contents.',
      },
      {
        name: 'filename',
        type: 'string',
        required: true,
        description: 'Its name.',
      },
    ],
    config_schema: {
      properties: {
        field: {
          type: 'string',
          title: 'File field',
          'x-civex': { kind: 'field', dtypes: ['file'] },
        } as never,
      },
      required: ['field'],
    },
  }),
  plugin({
    id: 'civex.parse_table',
    name: 'Read a table from a file',
    inputs: [
      {
        name: 'bytes',
        type: 'bytes',
        required: true,
        description: 'Raw file bytes.',
      },
    ],
    outputs: [
      {
        name: 'table',
        type: 'table',
        required: true,
        description: 'The table.',
      },
    ],
    config_schema: {
      properties: {
        delimiter: {
          type: 'string',
          default: ',',
          title: 'Columns separated by',
          'x-civex': {
            kind: 'choice',
            choices: [
              { value: ',', label: 'Commas' },
              { value: 'tab', label: 'Tabs' },
            ],
          },
        } as never,
        encoding: {
          type: 'string',
          default: 'utf-8',
          title: 'Text encoding',
          'x-civex': { advanced: true },
        } as never,
      },
    },
  }),
]

const SCHEMAS: Schema[] = [
  {
    id: 's1',
    name: 'recording',
    label: 'Recording',
    description: null,
    parent_id: null,
    display_template: null,
    fields: [
      {
        id: 'f1',
        name: 'audio',
        label: 'Audio',
        type: 'file',
        required: false,
        restrictions: {},
        default: null,
        position: 0,
      },
      {
        id: 'f2',
        name: 'notes',
        label: 'Notes',
        type: 'string',
        required: false,
        restrictions: {},
        default: null,
        position: 1,
      },
    ],
    deleted_at: null,
  },
]

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      async () =>
        new Response('[]', { headers: { 'Content-Type': 'application/json' } }),
    ),
  )
})
afterEach(() => vi.unstubAllGlobals())

let latest: WorkflowDraft
const keep = (d: WorkflowDraft) => {
  latest = d
}
function Harness({ initial }: { initial: WorkflowDraft }) {
  const [draft, setDraft] = useState(initial)
  return (
    <WorkflowBuilder
      draft={draft}
      onChange={(next) => {
        keep(next)
        setDraft(next)
      }}
      plugins={PLUGINS}
      schemas={SCHEMAS}
      collections={[]}
      errors={new Map()}
      showMissing={false}
    />
  )
}

function renderIt(initial: WorkflowDraft) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Harness initial={initial} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('WorkflowBuilder', () => {
  it('names a new step for its action and wires it to the step before', async () => {
    const user = userEvent.setup()
    renderIt({ ...emptyDraft(), name: 'Tables', schema: 'recording' })

    await user.click(screen.getByRole('button', { name: /Add a step/ }))
    await user.selectOptions(
      screen.getByLabelText('What it does'),
      'civex.load_file',
    )
    await user.click(screen.getByRole('button', { name: /Add a step/ }))
    const second = screen.getAllByLabelText('What it does')[1]
    await user.selectOptions(second, 'civex.parse_table')

    expect(latest.steps.map((s) => s.id)).toEqual([
      'read_a_file',
      'read_a_table_from_a_file',
    ])
    expect(latest.steps[1].inputs).toEqual({ bytes: 'read_a_file.bytes' })
  })

  it('offers only the fields a setting can take, by name', async () => {
    const user = userEvent.setup()
    renderIt({
      ...emptyDraft(),
      name: 'x',
      schema: 'recording',
      steps: [
        {
          id: 'read',
          plugin: 'civex.load_file',
          config: {},
          inputs: {},
          condition: '',
        },
      ],
    })
    const picker = screen.getByLabelText(/File field/)
    const options = within(picker)
      .getAllByRole('option')
      .map((o) => o.textContent)
    expect(options).toEqual(['— choose a field —', 'Audio'])
    await user.selectOptions(picker, 'audio')
    expect(latest.steps[0].config).toEqual({ field: 'audio' })
  })

  it('keeps rare settings under More settings and choices as a list', () => {
    renderIt({
      ...emptyDraft(),
      name: 'x',
      schema: 'recording',
      steps: [
        {
          id: 'parse',
          plugin: 'civex.parse_table',
          config: {},
          inputs: {},
          condition: '',
        },
      ],
    })
    expect(screen.queryByLabelText(/Text encoding/)).toBeNull()
    expect(
      screen.getByRole('button', { name: /More settings/ }),
    ).toBeInTheDocument()
    // The default is shown by its name, not the character.
    expect(screen.getByLabelText(/Columns separated by/)).toHaveDisplayValue(
      'Commas',
    )
  })

  it('warns that watching every field can start it again when it saves', async () => {
    const user = userEvent.setup()
    const saving = plugin({
      id: 'civex.save_field',
      name: 'Set a field',
      capabilities: ['update_record'],
    })
    PLUGINS.push(saving)
    try {
      renderIt({
        ...emptyDraft(),
        name: 'x',
        schema: 'recording',
        steps: [
          {
            id: 'set',
            plugin: 'civex.save_field',
            config: {},
            inputs: {},
            condition: '',
          },
        ],
      })
      await user.click(
        screen.getByRole('checkbox', { name: /When a Recording changes/ }),
      )
      expect(
        screen.getByText(/can start it again by its own save/),
      ).toBeInTheDocument()
    } finally {
      PLUGINS.pop()
    }
  })
})
