import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router'
import { ToastProvider } from '../ui/ToastProvider'
import { fakeServer, json, plan } from '../files/testSupport'
import { ExportBuilder } from './ExportDefinitionBuilder'
import { definition, ENCOUNTER, SCHEMAS } from './exportsTestSupport'

afterEach(() => vi.unstubAllGlobals())

const preview = (over: Record<string, unknown> = {}) => ({
  ...plan({ total: 2, available: 2 }),
  items: [
    { path: 'a.contour', size: 1, available: true, volume: 'default' },
    { path: 'b.contour', size: 1, available: true, volume: 'default' },
  ],
  ...over,
})

function serve(extra: Record<string, unknown> = {}) {
  return fakeServer({
    '/api/schemas/encounter/exports': () => json(definition(), 201),
    '/api/schemas/encounter/exports/Contours': () => json(definition()),
    '/api/file-access/plan': () => json(preview()),
    ...extra,
  })
}

function renderIt(props: { editing?: ReturnType<typeof definition> } = {}) {
  const onDone = vi.fn()
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter>
          <ExportBuilder
            schemas={SCHEMAS}
            attach={{ schema: ENCOUNTER, editing: props.editing }}
            onDone={onDone}
          />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
  return onDone
}

const next = () =>
  userEvent.click(screen.getByRole('button', { name: /^next/i }))
const back = () =>
  userEvent.click(screen.getByRole('button', { name: /^back/i }))
const section = (name: string) => screen.getByRole('region', { name })
const chip = (level: string, name: RegExp) =>
  within(screen.getByRole('group', { name: `${level} files` })).getByRole(
    'checkbox',
    { name },
  ) as HTMLInputElement
// The files, as chips on each level. These make exactly the ones named the ones
// that are on (what choosing a kind of record used to do).
const FILES = [
  ['Recording', 'audio'],
  ['Selection', 'contour'],
  ['Selection', 'table'],
] as const
async function onlyFiles(...keep: string[]) {
  for (const [level, name] of FILES) {
    const button = chip(level, new RegExp(name, 'i'))
    const on = button.checked
    if (on !== keep.includes(name)) await userEvent.click(button)
  }
}
const chooseKind = (kind: 'recording' | 'selection') =>
  kind === 'selection' ? onlyFiles('contour', 'table') : onlyFiles('audio')
const layout = (name: RegExp) => screen.getByRole('radio', { name })
const bodyOf = (
  calls: { path: string; method: string; body: Record<string, unknown> }[],
  method: string,
) => calls.filter((c) => c.method === method).pop()?.body

describe('the export builder, step by step', () => {
  it('shows the way ahead and starts on the files', () => {
    serve()
    renderIt()

    const steps = screen.getByRole('list')
    expect(within(steps).getByText('What')).toBeTruthy()
    expect(within(steps).getByText('Layout')).toBeTruthy()
    expect(within(steps).getByText('Finish')).toBeTruthy()
    expect(section('Selection')).toBeTruthy()
    expect(
      (screen.getByRole('button', { name: /^back/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(true)
    expect(screen.getByRole('button', { name: /next: layout/i })).toBeTruthy()
  })

  it('is about the schema: there is no collection or record to pick', () => {
    serve()
    renderIt()

    expect(screen.queryByRole('combobox', { name: /collection/i })).toBeNull()
    expect(screen.queryByText(/inside a record/i)).toBeNull()
    expect(screen.queryByPlaceholderText(/search/i)).toBeNull()
  })

  it('does not explain itself at length', () => {
    serve()
    renderIt()

    const text = document.body.textContent ?? ''
    expect(text).not.toMatch(/terminal/i)
    expect(text).not.toMatch(/civex schema exports/i)
  })

  it('shows a level for the schema and each kind beneath it, in order', () => {
    serve()
    renderIt()

    expect(
      screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent),
    ).toEqual(['Encounter', 'Recording', 'Selection'])
  })

  it('has every file on to begin with, and a chip turns one off', async () => {
    serve()
    renderIt()
    expect(chip('Recording', /audio/i).checked).toBe(true)
    expect(chip('Selection', /contour/i).checked).toBe(true)

    await userEvent.click(chip('Selection', /contour/i))

    expect(chip('Selection', /contour/i).checked).toBe(false)
    expect(chip('Selection', /table/i).checked).toBe(true)
    await userEvent.click(chip('Selection', /contour/i))
    expect(chip('Selection', /contour/i).checked).toBe(true)
  })

  it('lists each level’s own files: an inherited one is on the level above', () => {
    serve()
    renderIt()

    const names = (level: string) =>
      within(screen.getByRole('group', { name: `${level} files` }))
        .getAllByRole('checkbox')
        .map((b) => b.getAttribute('aria-label'))
    expect(names('Recording')).toEqual(['Audio'])
    expect(names('Selection')).toEqual(['Contour', 'Table'])
    expect(screen.queryByRole('group', { name: 'Encounter files' })).toBeNull()
  })

  it('offers a filter only when the files come from one kind', async () => {
    serve()
    renderIt()
    expect(screen.queryByRole('button', { name: /^Only some/ })).toBeNull()

    await chooseKind('selection')

    expect(
      screen.getByRole('button', { name: 'Only some Selections…' }),
    ).toBeTruthy()
  })

  it('asks for something to include when nothing is', async () => {
    serve()
    renderIt()

    await onlyFiles()

    expect(screen.getByText(/choose something to include/i)).toBeTruthy()
    expect(
      (screen.getByRole('button', { name: /^next/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(true)
  })

  it('moves forward and back, keeping what was chosen', async () => {
    serve()
    renderIt()
    await onlyFiles('contour')

    await next()
    expect(screen.getByRole('radiogroup', { name: 'Layout' })).toBeTruthy()
    await back()

    expect(chip('Selection', /contour/i).checked).toBe(true)
    expect(chip('Selection', /table/i).checked).toBe(false)
    expect(chip('Recording', /audio/i).checked).toBe(false)
  })
})

describe('the kind it starts from', () => {
  it('is one plain choice at the top, with the kinds as they nest', () => {
    serve()
    renderIt()

    const select = screen.getByLabelText('Starts from') as HTMLSelectElement
    expect(Array.from(select.options).map((o) => o.text.trim())).toEqual([
      'Encounter',
      'Recording',
      'Selection',
    ])
    // Indented by how deep each is, so the nesting can be seen.
    expect(select.options[2].text.startsWith('\u00A0\u00A0\u00A0\u00A0')).toBe(
      true,
    )
    expect(select.value).toBe('encounter')
    expect(screen.queryByLabelText('Offered from')).toBeNull()
  })

  it('says what that means: what it takes and where it is offered', () => {
    serve()
    renderIt()

    expect(
      screen.getByText(
        /It takes Encounter and everything inside it, and is offered on every Encounter, Recording and Selection page and on collections that use them\./,
      ),
    ).toBeTruthy()
  })

  it('changes the folders to choose among, starting the choices again', async () => {
    const calls = serve()
    renderIt()
    await userEvent.click(
      screen.getByRole('checkbox', { name: 'All Selections in one table' }),
    )

    await userEvent.selectOptions(
      screen.getByLabelText('Starts from'),
      'recording',
    )

    expect(
      screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent),
    ).toEqual(['Recording', 'Selection'])
    expect(
      (
        screen.getByRole('checkbox', {
          name: 'All Selections in one table',
        }) as HTMLInputElement
      ).checked,
    ).toBe(false)
    await next()
    await next()
    await userEvent.type(screen.getByRole('textbox', { name: 'Name' }), 'X')
    await userEvent.click(
      screen.getByRole('button', { name: /^save export$/i }),
    )
    await waitFor(() =>
      expect(
        calls.some(
          (c) =>
            c.method === 'POST' && c.path === '/api/schemas/recording/exports',
        ),
      ).toBe(true),
    )
  })

  it('is fixed once the export exists: it can be changed, but not what it starts from', () => {
    serve()
    renderIt({ editing: definition() })

    expect(screen.queryByLabelText('Starts from')).toBeNull()
    expect(screen.getByText('Starts from')).toBeTruthy()
    expect(screen.getAllByText('Encounter').length).toBeGreaterThan(0)
  })
})

describe('choosing a layout', () => {
  it('shows each one as the folders it makes, in neutral names', async () => {
    serve()
    renderIt()
    await next()

    const tree = screen.getByLabelText(/a folder per record example/i)
    const grouped = screen.getByLabelText(/grouped by kind example/i)
    const flat = screen.getByLabelText(/all in one folder example/i)

    expect(within(tree).getByText('Child 1')).toBeTruthy()
    expect(within(tree).getAllByText('file.txt')).toHaveLength(2)
    expect(within(tree).queryByText('Items')).toBeNull()
    expect(within(grouped).getByText('Items')).toBeTruthy()
    expect(within(grouped).getByText('Item 2 - file.txt')).toBeTruthy()
    expect(within(flat).queryByText('Parent 1')).toBeNull()
    expect(within(flat).getAllByText(/ - file\.txt$/)).toHaveLength(3)
    // Nothing tied to anyone’s own record types.
    expect(document.body.textContent).not.toMatch(
      /encounter 1|recording 1|selection 1/i,
    )
  })

  it('selects one, a folder per record to begin with', async () => {
    serve()
    renderIt()
    await next()

    expect((layout(/a folder per record/i) as HTMLInputElement).checked).toBe(
      true,
    )
    await userEvent.click(layout(/grouped by kind/i))

    expect((layout(/grouped by kind/i) as HTMLInputElement).checked).toBe(true)
    expect((layout(/a folder per record/i) as HTMLInputElement).checked).toBe(
      false,
    )
  })
})

describe('reviewing', () => {
  async function toReview() {
    await next()
    await next()
  }

  it('shows what it takes and where it will be available, briefly', async () => {
    serve()
    renderIt()
    await onlyFiles('contour')
    await next()
    await userEvent.click(layout(/all in one folder/i))
    await next()

    expect(
      screen.getByText('contour of Selection · all in one folder'),
    ).toBeTruthy()
    expect(
      screen.getByText('Collections · Encounter · Recording · Selection'),
    ).toBeTruthy()
  })

  it('previews against your data on its own, and again when the choices change', async () => {
    const calls = serve()
    renderIt()
    await chooseKind('selection')
    await toReview()

    // No button to press: it is worked out as soon as the last step is shown.
    expect(await screen.findByText('a.contour')).toBeTruthy()
    expect(screen.queryByRole('button', { name: /^preview$/i })).toBeNull()
    expect(bodyOf(calls, 'POST')).toMatchObject({
      schema_name: 'selection',
      layout: 'tree',
      include_items: true,
    })
    await back()
    await back()
    await chooseKind('recording')
    await toReview()

    await waitFor(() =>
      expect(bodyOf(calls, 'POST')).toMatchObject({ schema_name: 'recording' }),
    )
    expect(screen.queryByText('Out of date')).toBeNull()
  })

  it('shows the tables in the folders they will be written in, with their rows', async () => {
    serve({
      '/api/file-access/plan': () =>
        json(
          preview({
            items: [
              {
                path: 'A/s1/s1.contour',
                size: 1,
                available: true,
                volume: 'd',
              },
            ],
            tables: [
              {
                name: 'Selections.csv',
                folder: 'A',
                path: 'A/Selections.csv',
                kind: 'selection',
                rows: 2,
                columns: ['id'],
                format: 'csv',
                shape: 'rows',
              },
            ],
          }),
        ),
    })
    renderIt()
    await toReview()

    const tree = await screen.findByRole('list', { name: 'Folder preview' })
    expect(within(tree).getByText('Selections.csv')).toBeTruthy()
    expect(within(tree).getByText('2 rows')).toBeTruthy()
    expect(within(tree).getByText('s1.contour')).toBeTruthy()
    expect(screen.getByText(/1 table/)).toBeTruthy()
  })

  it('previews an any-kind export within the schema’s own tree', async () => {
    const calls = serve()
    renderIt()
    await toReview()

    await waitFor(() => expect(bodyOf(calls, 'POST')).toBeTruthy())
    expect(bodyOf(calls, 'POST')).toMatchObject({
      kinds: ['encounter', 'recording', 'selection'],
    })
    expect(bodyOf(calls, 'POST')?.schema_name).toBeUndefined()
  })

  it('shows why a preview failed', async () => {
    serve({
      '/api/file-access/plan': () =>
        json(
          { detail: "None of the selected records has a file field named 'x'" },
          422,
        ),
    })
    renderIt()
    await toReview()

    expect(
      await screen.findByText(/none of the selected records has a file field/i),
    ).toBeTruthy()
  })
})

describe('saving', () => {
  it('needs a name, then saves the export with the schema', async () => {
    const calls = serve()
    const onDone = renderIt()
    await onlyFiles('contour')
    await next()
    await userEvent.click(layout(/grouped by kind/i))
    await next()
    const save = screen.getByRole('button', { name: /^save export$/i })
    expect((save as HTMLButtonElement).disabled).toBe(true)

    await userEvent.type(
      screen.getByRole('textbox', { name: 'Name' }),
      'Contours',
    )
    await userEvent.click(save)

    await waitFor(() => expect(onDone).toHaveBeenCalled())
    expect(
      calls.find(
        (c) =>
          c.method === 'POST' && c.path === '/api/schemas/encounter/exports',
      )?.body,
    ).toEqual({
      name: 'Contours',
      holder: 'selection',
      fields: ['contour'],
      filter_tree: null,
      files_layout: 'grouped',
      include_files: true,
      tables: [],
    })
  })

  it('shows why a save was refused, and stays put', async () => {
    serve({
      '/api/schemas/encounter/exports': () =>
        json(
          {
            detail:
              "An export called 'Contours' already exists on 'encounter'.",
          },
          409,
        ),
    })
    const onDone = renderIt()
    await next()
    await next()
    await userEvent.type(
      screen.getByRole('textbox', { name: 'Name' }),
      'Contours',
    )

    await userEvent.click(
      screen.getByRole('button', { name: /^save export$/i }),
    )

    expect((await screen.findByRole('alert')).textContent).toMatch(
      /already exists/i,
    )
    expect(onDone).not.toHaveBeenCalled()
  })
})

describe('changing an export', () => {
  it('starts from what it is now, and sends the change, renamed if it was', async () => {
    const calls = serve()
    const onDone = renderIt({ editing: definition() })
    expect(chip('Selection', /contour/i).checked).toBe(true)
    expect(chip('Selection', /table/i).checked).toBe(false)
    expect(chip('Recording', /audio/i).checked).toBe(false)
    await next()
    expect((layout(/all in one folder/i) as HTMLInputElement).checked).toBe(
      true,
    )
    await userEvent.click(layout(/grouped by kind/i))
    await next()
    const name = screen.getByRole('textbox', {
      name: 'Name',
    }) as HTMLInputElement
    expect(name.value).toBe('Contours')
    await userEvent.clear(name)
    await userEvent.type(name, 'Contour files')

    await userEvent.click(
      screen.getByRole('button', { name: /^save changes$/i }),
    )

    await waitFor(() => expect(onDone).toHaveBeenCalled())
    const sent = calls.find((c) => c.method === 'PATCH')!
    expect(sent.path).toBe('/api/schemas/encounter/exports/Contours')
    expect(sent.body).toMatchObject({
      rename: 'Contour files',
      holder: 'selection',
      fields: ['contour'],
      files_layout: 'grouped',
    })
  })

  it('does not rename when the name is the same', async () => {
    const calls = serve()
    renderIt({ editing: definition() })
    await next()
    await next()

    await userEvent.click(
      screen.getByRole('button', { name: /^save changes$/i }),
    )

    await waitFor(() =>
      expect(calls.some((c) => c.method === 'PATCH')).toBe(true),
    )
    expect(calls.find((c) => c.method === 'PATCH')!.body.rename).toBeUndefined()
  })
})
