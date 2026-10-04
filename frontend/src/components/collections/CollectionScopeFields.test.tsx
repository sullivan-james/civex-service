import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { CollectionScopeFields } from './CollectionScopeFields'

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    headers: { 'Content-Type': 'application/json' },
  })

const schema = (id: string, name: string, parent_id: string | null = null) => ({
  id,
  name,
  label: null,
  parent_id,
  deleted_at: null,
  fields: [],
})
// species, site and recording are top-level; selection is a child of recording.
const SCHEMAS = [
  schema('1', 'species'),
  schema('2', 'site'),
  schema('3', 'recording'),
  schema('4', 'selection', '3'),
  schema('5', 'zebra'),
]

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input), 'http://x').pathname
      return path === '/api/schemas' ? json(SCHEMAS) : json({})
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

function setup(selected: string[] = []) {
  const onSchemasChange = vi.fn()
  render(
    <QueryClientProvider client={new QueryClient()}>
      <CollectionScopeFields
        scope="local"
        onScopeChange={() => {}}
        schemas={selected}
        onSchemasChange={onSchemasChange}
      />
    </QueryClientProvider>,
  )
  return onSchemasChange
}

const box = async (name: string) =>
  (await screen.findByText(name, { selector: 'span' }))
    .closest('label')!
    .querySelector('input')!

describe('CollectionScopeFields: shift-click over the schema list', () => {
  it('ticks every schema from one to another', async () => {
    const onChange = setup()
    const user = userEvent.setup()

    await user.click(await box('Species'))
    await user.keyboard('{Shift>}')
    await user.click(await box('Recording'))
    await user.keyboard('{/Shift}')

    expect(onChange).toHaveBeenLastCalledWith(['recording', 'site', 'species'])
  })

  it('brings a child schema its parent, as a single click does', async () => {
    const onChange = setup()
    const user = userEvent.setup()

    // From site down to selection: the range includes the child, whose parent
    // (recording) is in the range too, and zebra is not.
    await user.click(await box('Site'))
    await user.keyboard('{Shift>}')
    await user.click(await box('Selection'))
    await user.keyboard('{/Shift}')

    expect(onChange).toHaveBeenLastCalledWith([
      'recording',
      'selection',
      'site',
    ])
  })

  it('ticks the parent even when the range starts below it', async () => {
    const onChange = setup()
    const user = userEvent.setup()

    await user.click(await box('Selection'))
    await user.keyboard('{Shift>}')
    await user.click(await box('Zebra'))
    await user.keyboard('{/Shift}')

    // selection needs recording, which sits above the start of the range.
    expect(onChange).toHaveBeenLastCalledWith([
      'recording',
      'selection',
      'zebra',
    ])
  })

  it('unticking a parent in the range unticks its children too', async () => {
    const onChange = setup(['recording', 'selection', 'site'])
    const user = userEvent.setup()

    await user.click(await box('Site'))
    await user.keyboard('{Shift>}')
    await user.click(await box('Recording'))
    await user.keyboard('{/Shift}')

    expect(onChange).toHaveBeenLastCalledWith([])
  })
})
