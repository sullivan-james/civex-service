import { useEffect, useState } from 'react'
import { render, screen, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import { emptyDraft, type Draft } from '../../utils/exportBuilder'
import { SCHEMAS } from './exportsTestSupport'
import { FilesStep } from './ExportSteps'

let latest: Draft
const remember = (d: Draft) => {
  latest = d
}

function Harness({
  initial = emptyDraft,
  scope = 'encounter',
}: {
  initial?: Draft
  scope?: string
}) {
  const [draft, setDraft] = useState(initial)
  useEffect(() => remember(draft), [draft])
  const [client] = useState(() => new QueryClient())
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <FilesStep
          schemas={SCHEMAS}
          scopeSchema={scope}
          draft={draft}
          set={(patch) => setDraft((d) => ({ ...d, ...patch }))}
        />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

const tick = (name: RegExp | string) =>
  screen.getByRole('checkbox', { name }) as HTMLInputElement
const level = (name: string) => screen.getByRole('region', { name })

const ALL_SELECTIONS = 'All Selections in one table'
const SELECTION_SHEET = 'A details sheet for each Selection'
const RECORDING_LIST = 'A table of each Recording’s Selections'

describe('what goes in the folder', () => {
  it('shows each kind as a card of its own, saying where it is, with no nesting to decode', () => {
    render(<Harness />)

    expect(
      screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent),
    ).toEqual(['Encounter', 'Recording', 'Selection'])
    expect(
      within(level('Encounter')).getByText('top of the export'),
    ).toBeTruthy()
    expect(
      within(level('Recording')).getByText('inside Encounter'),
    ).toBeTruthy()
    expect(
      within(level('Selection')).getByText('inside Encounter › Recording'),
    ).toBeTruthy()
    // Every card is the same width: nothing is indented.
    for (const name of ['Encounter', 'Recording', 'Selection'])
      expect(level(name).getAttribute('style') ?? '').not.toMatch(/margin/)
  })

  it('shows each table as a row to choose, in plain words, with what it means', () => {
    render(<Harness />)

    const recording = within(level('Recording'))
    expect(recording.getByLabelText('All Recordings in one table')).toBeTruthy()
    expect(
      recording.getByLabelText('A details sheet for each Recording'),
    ).toBeTruthy()
    expect(recording.getByLabelText(RECORDING_LIST)).toBeTruthy()
    // What each means is in an info tip beside it, so the rows stay slim.
    expect(
      within(
        screen.getByRole('group', { name: 'Recording tables' }),
      ).getAllByRole('button', { name: 'More information' }),
    ).toHaveLength(3)
    // The last level has nothing inside it to list.
    expect(
      within(level('Selection')).queryByLabelText(/^A table of each/),
    ).toBeNull()
  })

  it('shows the files to take as rows too, each a full-row choice', async () => {
    render(<Harness />)

    const files = within(screen.getByRole('group', { name: 'Selection files' }))
    expect(files.getAllByRole('checkbox')).toHaveLength(2)
    expect((files.getByLabelText('Contour') as HTMLInputElement).checked).toBe(
      true,
    )

    // The whole row is the target, not only the box.
    await userEvent.click(files.getByText('Contour'))

    expect((files.getByLabelText('Contour') as HTMLInputElement).checked).toBe(
      false,
    )
  })

  it('has no technical vocabulary to learn, and no format that applies to all', () => {
    render(<Harness />)

    const text = document.body.textContent ?? ''
    expect(text).not.toMatch(/holder|which records|kind taken/i)
    expect(screen.queryByRole('combobox', { name: 'Records' })).toBeNull()
    expect(screen.queryByLabelText('Tables as')).toBeNull()
  })

  it('ticks a details sheet for each selection: its own fields, in its folder', async () => {
    render(<Harness />)

    await userEvent.click(tick(SELECTION_SHEET))

    expect(latest.tables).toEqual([
      {
        format: 'csv',
        columns: null,
        kind: 'selection',
        where: 'selection',
        shape: 'fields',
      },
    ])
    expect(tick(SELECTION_SHEET).checked).toBe(true)
  })

  it('ticks a list of each recording’s selections, and needs a folder per record', async () => {
    render(<Harness initial={{ ...emptyDraft, layout: 'flat' }} />)

    await userEvent.click(tick(RECORDING_LIST))

    expect(latest.tables).toEqual([
      { format: 'csv', columns: null, kind: 'selection', where: 'recording' },
    ])
    expect(latest.layout).toBe('tree')
  })

  it('ticks one table of everything at the top without touching the layout', async () => {
    render(<Harness initial={{ ...emptyDraft, layout: 'flat' }} />)

    await userEvent.click(tick(ALL_SELECTIONS))

    expect(latest.tables).toEqual([
      { format: 'csv', columns: null, kind: 'selection' },
    ])
    expect(latest.layout).toBe('flat')
  })

  it('unticks it again', async () => {
    render(<Harness />)
    await userEvent.click(tick(ALL_SELECTIONS))

    await userEvent.click(tick(ALL_SELECTIONS))

    expect(latest.tables).toEqual([])
  })

  it('reads a saved export back as ticks', () => {
    render(
      <Harness
        initial={{
          ...emptyDraft,
          holder: 'selection',
          fields: ['contour'],
          tables: [
            {
              format: 'csv',
              kind: 'selection',
              where: 'selection',
              shape: 'fields',
            },
            { format: 'csv', kind: 'selection', where: 'recording' },
          ],
        }}
      />,
    )

    expect(tick(SELECTION_SHEET).checked).toBe(true)
    expect(tick(RECORDING_LIST).checked).toBe(true)
    expect(tick(ALL_SELECTIONS).checked).toBe(false)
    const files = within(screen.getByRole('group', { name: 'Selection files' }))
    expect((files.getByLabelText('Contour') as HTMLInputElement).checked).toBe(
      true,
    )
    expect((files.getByLabelText('Table') as HTMLInputElement).checked).toBe(
      false,
    )
  })

  it('says when nothing is included', async () => {
    render(<Harness />)

    for (const group of ['Recording files', 'Selection files'])
      for (const box of within(
        screen.getByRole('group', { name: group }),
      ).getAllByRole('checkbox'))
        await userEvent.click(box)

    expect(screen.getByText(/choose something to include/i)).toBeTruthy()
    await userEvent.click(tick(ALL_SELECTIONS))
    expect(screen.queryByText(/choose something to include/i)).toBeNull()
  })
})

describe('each table’s own format and name', () => {
  it('appear only while the table is on', async () => {
    render(<Harness />)
    expect(screen.queryByLabelText(`${ALL_SELECTIONS}: format`)).toBeNull()

    await userEvent.click(tick(ALL_SELECTIONS))

    expect(screen.getByLabelText(`${ALL_SELECTIONS}: format`)).toBeTruthy()
    expect(screen.getByLabelText(`${ALL_SELECTIONS}: file name`)).toBeTruthy()
  })

  it('give each table its own format', async () => {
    render(<Harness />)
    await userEvent.click(tick(ALL_SELECTIONS))
    await userEvent.click(tick(SELECTION_SHEET))

    await userEvent.selectOptions(
      screen.getByLabelText(`${SELECTION_SHEET}: format`),
      'xlsx',
    )

    expect(latest.tables.map((t) => [t.kind, t.format])).toEqual([
      ['selection', 'csv'],
      ['selection', 'xlsx'],
    ])
  })

  it('name the table of all of a kind, and say what it is called otherwise', async () => {
    render(<Harness />)
    await userEvent.click(tick('All Recordings in one table'))

    const name = screen.getByLabelText('All Recordings in one table: file name')
    expect(name).toHaveAttribute('placeholder', 'Recordings')
    await userEvent.type(name, 'Every recording')

    expect(latest.tables[0]).toMatchObject({
      kind: 'recording',
      name: 'Every recording',
    })
  })

  it('name a table written in folders from a template over the folder’s record', async () => {
    render(<Harness />)
    await userEvent.click(tick(RECORDING_LIST))
    const name = screen.getByLabelText(`${RECORDING_LIST}: file name`)
    expect(name).toHaveAttribute('placeholder', 'Selections')
    await userEvent.type(name, '{{rname} selections')

    expect(latest.tables[0].name).toBe('{rname} selections')
  })

  it('keep the name and format when other ticks change', async () => {
    render(<Harness />)
    await userEvent.click(tick(ALL_SELECTIONS))
    await userEvent.type(
      screen.getByLabelText(`${ALL_SELECTIONS}: file name`),
      'All',
    )

    await userEvent.click(tick(SELECTION_SHEET))

    expect(latest.tables[0].name).toBe('All')
  })
})

describe('choosing columns, on the table’s own row', () => {
  it('shows every column to begin with, and opens a panel to choose from', async () => {
    render(<Harness />)
    await userEvent.click(tick(ALL_SELECTIONS))
    const open = screen.getByRole('button', {
      name: `${ALL_SELECTIONS}: columns`,
    })
    expect(open).toHaveTextContent('All columns')

    await userEvent.click(open)

    expect(screen.getByText(/^Shown \(/)).toBeTruthy()
    expect(screen.getByText('Not shown')).toBeTruthy()
  })

  it('keeps the table as it is until a column is changed', async () => {
    render(<Harness />)
    await userEvent.click(tick(ALL_SELECTIONS))
    await userEvent.click(
      screen.getByRole('button', { name: `${ALL_SELECTIONS}: columns` }),
    )

    expect(latest.tables[0].columns).toBeNull()
    await userEvent.click(screen.getByLabelText('Show Quality'))

    expect(latest.tables[0].columns).toEqual(
      expect.not.arrayContaining(['quality']),
    )
    expect(latest.tables[0].columns).toContain('id')
    expect(
      screen.getByRole('button', { name: `${ALL_SELECTIONS}: columns` }),
    ).toHaveTextContent(/\d+ columns/)
  })

  it('offers the record’s own id and dates beside its fields', async () => {
    render(<Harness />)
    await userEvent.click(tick(ALL_SELECTIONS))
    await userEvent.click(
      screen.getByRole('button', { name: `${ALL_SELECTIONS}: columns` }),
    )

    expect(screen.getByLabelText('Show Record id')).toBeTruthy()
    await userEvent.click(screen.getByLabelText('Show Created'))
    expect(latest.tables[0].columns).toContain('created_at')
  })

  it('can go back to every column', async () => {
    render(<Harness />)
    await userEvent.click(tick(ALL_SELECTIONS))
    await userEvent.click(
      screen.getByRole('button', { name: `${ALL_SELECTIONS}: columns` }),
    )
    await userEvent.click(screen.getByLabelText('Show Quality'))

    await userEvent.click(
      screen.getByRole('button', { name: 'Use every column' }),
    )

    expect(latest.tables[0].columns).toBeNull()
  })

  it('says when no column is left, since a table needs one', async () => {
    render(<Harness />)
    await userEvent.click(tick(ALL_SELECTIONS))
    await userEvent.click(
      screen.getByRole('button', { name: `${ALL_SELECTIONS}: columns` }),
    )

    await userEvent.click(screen.getByRole('button', { name: 'Hide all' }))

    expect(screen.getByText('Choose at least one column.')).toBeTruthy()
  })

  it('is for a table of one kind: there is nothing to choose for each kind taken', () => {
    render(
      <Harness
        initial={{ ...emptyDraft, tables: [{ format: 'csv', columns: null }] }}
      />,
    )

    expect(screen.queryByRole('button', { name: /: columns$/ })).toBeNull()
  })
})

describe('a list in each folder', () => {
  it('can also be made where a folder has nothing to list', async () => {
    render(<Harness />)
    await userEvent.click(tick(RECORDING_LIST))

    await userEvent.click(
      screen.getByLabelText(
        `${RECORDING_LIST}: also where there is nothing to list`,
      ),
    )

    expect(latest.tables[0].skip_empty).toBe(false)
  })

  it('has no such option for a table at the top or a details sheet', async () => {
    render(<Harness />)
    await userEvent.click(tick(ALL_SELECTIONS))
    await userEvent.click(tick(SELECTION_SHEET))

    expect(
      screen.queryByLabelText(/also where there is nothing to list/),
    ).toBeNull()
  })
})

describe('only some of the records', () => {
  const one = {
    ...emptyDraft,
    holder: 'selection',
    fields: ['contour'],
  }

  it('is offered in the level the files come from, when it is the only one', () => {
    render(<Harness initial={one} />)

    expect(
      within(level('Selection')).getByRole('button', {
        name: 'Only some Selections…',
      }),
    ).toBeTruthy()
    expect(
      within(level('Recording')).queryByRole('button', { name: /^Only some/ }),
    ).toBeNull()
  })

  it('opens the conditions when asked for', async () => {
    render(<Harness initial={one} />)

    await userEvent.click(
      screen.getByRole('button', { name: 'Only some Selections…' }),
    )

    expect(screen.getByText('Only Selections where')).toBeTruthy()
  })

  it('is not offered when the files come from several kinds', () => {
    render(<Harness />)

    expect(screen.queryByRole('button', { name: /^Only some/ })).toBeNull()
  })
})

describe('tables the choices above do not stand for', () => {
  it('are listed on their own, and can be taken out', async () => {
    render(
      <Harness
        initial={{
          ...emptyDraft,
          tables: [{ format: 'csv', columns: ['id'] }],
        }}
      />,
    )

    const row = screen.getByText('Other tables').closest('div')!.parentElement!
    expect(
      within(row).getByText(/CSV of each kind taken at the top/),
    ).toBeTruthy()

    await userEvent.click(
      within(row).getByRole('checkbox', { name: /CSV of each kind taken/ }),
    )

    expect(latest.tables).toEqual([])
  })

  it('keep their format and name editable', async () => {
    render(
      <Harness
        initial={{
          ...emptyDraft,
          tables: [{ format: 'csv', columns: ['id'] }],
        }}
      />,
    )

    await userEvent.selectOptions(
      screen.getByLabelText(/CSV of each kind taken at the top.*: format/),
      'xlsx',
    )

    expect(latest.tables[0].format).toBe('xlsx')
  })

  it('are not shown when there are none', () => {
    render(<Harness />)

    expect(screen.queryByText('Other tables')).toBeNull()
  })
})

describe('everything is in the one editor', () => {
  it('has no panel of more options to open', () => {
    render(<Harness />)

    expect(screen.queryByRole('button', { name: /more options/i })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Add a table' })).toBeNull()
  })
})
