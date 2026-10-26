import { describe, it, expect, vi } from 'vitest'
import { useCallback, useState } from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { schemasApi } from '../../api/schemas'
import { CONTROLS } from './controlRegistry'
import type { ControlContext, Rules } from './RestrictionControls'
import type { RestrictionDescriptor } from '../../api/schemas'

const ctx: ControlContext = {
  schemaName: 's',
  fields: [{ name: 'deployment_id', label: 'Deployment', dtype: 'string' }],
  schemas: [],
}

function desc(
  key: string,
  control: string,
  label = key,
): RestrictionDescriptor {
  return { key, label, control, help: '' }
}

/** Mounts one control and exposes the rules it produced and its problems. */
function Harness({
  d,
  initial = {},
  context = ctx,
}: {
  d: RestrictionDescriptor
  initial?: Rules
  context?: ControlContext
}) {
  const [rules, setRules] = useState<Rules>(initial)
  const [problems, setProblems] = useState<Record<string, string | null>>({})
  const set = useCallback((key: string, value: unknown) => {
    setRules((prev) => {
      const next = { ...prev }
      if (value === undefined) delete next[key]
      else next[key] = value
      return next
    })
  }, [])
  const problem = useCallback(
    (key: string, m: string | null) =>
      setProblems((p) => (p[key] === m ? p : { ...p, [key]: m })),
    [],
  )
  const Control = CONTROLS[d.control]
  return (
    <QueryClientProvider client={queryClient}>
      <Control
        desc={d}
        rules={rules}
        set={set}
        problem={problem}
        ctx={context}
      />
      <output data-testid="rules">{JSON.stringify(rules)}</output>
      <output data-testid="problems">
        {JSON.stringify(Object.values(problems).filter(Boolean))}
      </output>
    </QueryClientProvider>
  )
}

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
})
vi.spyOn(schemasApi, 'previewName').mockResolvedValue({
  name: 'preview',
  error: null,
})
// The server runs the patterns; this stands in for it with canned answers.
const PATTERN_PROBLEMS: Record<string, string> = {
  HHmmSS: 'a datetime pattern needs the tokens YYYY MM DD',
  'YYYYMMDD_HHmmSS(': 'not a valid regular expression',
}
const NAME_GIVES: Record<string, unknown> = {
  'rec_take_07.wav': 7,
  'site_2024-03-15.csv': '2024-03-15T00:00:00',
  '15032024_093000.csv': '2024-03-15T09:30:00',
}
const previewFromFilename = vi
  .spyOn(schemasApi, 'previewFromFilename')
  .mockImplementation(async ({ filename, patterns }) => {
    const problems = patterns.map((p) => PATTERN_PROBLEMS[p] ?? null)
    const value =
      problems.some(Boolean) || !filename
        ? null
        : (NAME_GIVES[filename] ?? null)
    return { problems, value, error: null }
  })

const rules = () => JSON.parse(screen.getByTestId('rules').textContent!)
const problems = () => JSON.parse(screen.getByTestId('problems').textContent!)

describe('number and bytes controls', () => {
  it('stores numbers and clears when emptied', async () => {
    render(<Harness d={desc('min', 'number', 'Smallest allowed')} />)
    const input = screen.getByLabelText('Smallest allowed')
    await userEvent.type(input, '-2.5')
    expect(rules()).toEqual({ min: -2.5 })
    await userEvent.clear(input)
    expect(rules()).toEqual({})
  })

  it('converts a size to bytes', async () => {
    render(<Harness d={desc('max_size', 'bytes', 'Largest file')} />)
    await userEvent.type(screen.getByLabelText('Largest file'), '5')
    expect(rules()).toEqual({ max_size: 5 * 1024 * 1024 })
    await userEvent.selectOptions(
      screen.getByLabelText('Largest file unit'),
      'GB',
    )
    expect(rules()).toEqual({ max_size: 5 * 1024 ** 3 })
  })

  it('shows an existing size in a sensible unit', () => {
    render(
      <Harness
        d={desc('max_size', 'bytes', 'Largest file')}
        initial={{ max_size: 2 * 1024 ** 2 }}
      />,
    )
    expect(screen.getByLabelText('Largest file')).toHaveValue(2)
    expect(screen.getByLabelText('Largest file unit')).toHaveValue('MB')
  })
})

describe('choices control', () => {
  it('adds and removes values', async () => {
    render(<Harness d={desc('choices', 'choices', 'Allowed values')} />)
    const input = screen.getByLabelText('New allowed value')
    await userEvent.type(input, 'left{Enter}')
    await userEvent.type(input, 'right, both{Enter}')
    expect(rules()).toEqual({ choices: ['left', 'right', 'both'] })
    await userEvent.click(screen.getByLabelText('Remove right'))
    expect(rules()).toEqual({ choices: ['left', 'both'] })
  })
})

describe('accept control', () => {
  it('builds the accept list from presets and extra extensions', async () => {
    render(<Harness d={desc('accept', 'accept', 'File types accepted')} />)
    await userEvent.click(screen.getByRole('button', { name: 'Audio' }))
    await userEvent.type(screen.getByLabelText('Other file extensions'), 'nc')
    expect(rules()).toEqual({ accept: 'audio/*,.nc' })
    await userEvent.click(screen.getByRole('button', { name: 'Audio' }))
    expect(rules()).toEqual({ accept: '.nc' })
  })

  it('recognises presets in an existing list', () => {
    render(
      <Harness
        d={desc('accept', 'accept')}
        initial={{ accept: '.gpx,.geojson,.parquet,.nc' }}
      />,
    )
    expect(screen.getByRole('button', { name: 'Tracks' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(screen.getByRole('button', { name: 'Audio' })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
    expect(screen.getByLabelText('Other file extensions')).toHaveValue('.nc')
  })
})

describe('unit and precision controls', () => {
  it('sets and clears a unit', async () => {
    render(<Harness d={desc('unit', 'unit', 'Unit')} />)
    const input = screen.getByLabelText('Unit')
    await userEvent.type(input, 'm')
    expect(rules()).toEqual({ unit: 'm' })
    await userEvent.clear(input)
    expect(rules()).toEqual({})
  })

  it('warns that changing a saved unit only relabels', async () => {
    const existing = {
      name: 'depth',
      restrictions: { unit: 'm' },
    } as unknown as ControlContext['existing']
    render(
      <Harness
        d={desc('unit', 'unit', 'Unit')}
        initial={{ unit: 'm' }}
        context={{ ...ctx, existing }}
      />,
    )
    expect(screen.queryByRole('alert')).toBeNull()
    const input = screen.getByLabelText('Unit')
    await userEvent.clear(input)
    await userEvent.type(input, 'ft')
    expect(screen.getByRole('alert')).toHaveTextContent(/Relabels m as ft/)
    expect(screen.getByRole('alert')).toHaveTextContent(/not converted/)
  })

  it('omits the default precision', async () => {
    render(<Harness d={desc('precision', 'precision', 'Least precise')} />)
    await userEvent.selectOptions(
      screen.getByLabelText('Least precise'),
      'month',
    )
    expect(rules()).toEqual({ precision: 'month' })
    await userEvent.selectOptions(screen.getByLabelText('Least precise'), 'day')
    expect(rules()).toEqual({})
  })
})

describe('date bounds', () => {
  it('accepts partial dates and flags nonsense', async () => {
    render(<Harness d={desc('min', 'date_bound', 'Earliest')} />)
    const input = screen.getByLabelText('Earliest')
    await userEvent.type(input, '2020-03')
    expect(rules()).toEqual({ min: '2020-03' })
    expect(problems()).toEqual([])
    await userEvent.clear(input)
    await userEvent.type(input, 'next spring')
    expect(problems()[0]).toMatch(/Earliest/)
  })
})

describe('datetime bounds', () => {
  it('stores wall time in the field zone as UTC', () => {
    render(
      <Harness
        d={desc('min', 'datetime_bound', 'Not before')}
        initial={{ timezone: 'America/Chicago' }}
      />,
    )
    fireEvent.change(screen.getByLabelText('Not before'), {
      target: { value: '2024-03-01T15:30' },
    })
    expect(rules()).toEqual({
      timezone: 'America/Chicago',
      min: '2024-03-01T21:30:00.000Z',
    })
  })

  it('refuses a time inside a clock change', () => {
    render(
      <Harness
        d={desc('min', 'datetime_bound', 'Not before')}
        initial={{ timezone: 'America/Chicago' }}
      />,
    )
    fireEvent.change(screen.getByLabelText('Not before'), {
      target: { value: '2024-03-10T02:30' },
    })
    expect(problems()[0]).toMatch(/Not before/)
    expect(rules()).toEqual({ timezone: 'America/Chicago' })
  })
})

describe('geometry controls', () => {
  it('toggles shapes', async () => {
    render(
      <Harness
        d={desc('geometry_types', 'geometry_types', 'Shapes allowed')}
      />,
    )
    await userEvent.click(screen.getByLabelText('Point'))
    await userEvent.click(screen.getByLabelText('Polygon'))
    expect(rules()).toEqual({ geometry_types: ['Point', 'Polygon'] })
    await userEvent.click(screen.getByLabelText('Point'))
    await userEvent.click(screen.getByLabelText('Polygon'))
    expect(rules()).toEqual({})
  })

  it('needs all four edges or none, and keeps latitudes sane', async () => {
    render(<Harness d={desc('bbox', 'bbox', 'Restrict to an area')} />)
    await userEvent.type(screen.getByLabelText(/West/), '-12')
    expect(problems()[0]).toMatch(/Fill in west, south, east and north/)
    await userEvent.type(screen.getByLabelText(/South/), '48')
    await userEvent.type(screen.getByLabelText(/East/), '4')
    await userEvent.type(screen.getByLabelText(/North/), '62')
    expect(rules()).toEqual({ bbox: [-12, 48, 4, 62] })
    expect(problems()).toEqual([])
    await userEvent.clear(screen.getByLabelText(/North/))
    await userEvent.type(screen.getByLabelText(/North/), '30')
    expect(problems()[0]).toMatch(/south below north/)
  })
})

describe('filename template and schema controls', () => {
  it('inserts field names into the template', async () => {
    render(
      <Harness
        d={desc('filename_template', 'filename_template', 'Download file name')}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Deployment' }))
    await userEvent.type(screen.getByLabelText('Download file name'), '_clip')
    // The extension is the file's own: nothing to insert for it.
    expect(screen.queryByRole('button', { name: /ext/ })).toBeNull()
    expect(rules()).toEqual({ filename_template: '{deployment_id}_clip' })
  })

  it('wants a target schema', async () => {
    const schemas = [
      { id: '1', name: 'patient', label: null },
      { id: '2', name: 's', label: null },
    ] as unknown as ControlContext['schemas']
    render(
      <Harness
        d={desc('schema', 'schema', 'Points at')}
        context={{ ...ctx, schemas }}
      />,
    )
    expect(problems()[0]).toMatch(/Pick the type of record/)
    await userEvent.selectOptions(screen.getByLabelText('Points at'), 'patient')
    expect(rules()).toEqual({ schema: 'patient' })
    expect(problems()).toEqual([])
    // the schema being edited can't point at itself
    expect(screen.queryByRole('option', { name: /^s$/ })).toBeNull()
  })
})

describe('fill from a file name', () => {
  const withFiles: ControlContext = {
    ...ctx,
    type: 'string',
    fields: [
      ...ctx.fields,
      { name: 'audio', label: 'Audio', dtype: 'file' },
      { name: 'track', label: 'Track', dtype: 'file', source: 'Encounter' },
    ],
  }
  const d = desc('from_filename', 'from_filename', "Fill from a file's name")

  it('offers the file fields, own and inherited, and wants a pattern', async () => {
    render(<Harness d={d} context={withFiles} />)
    expect(screen.queryByRole('option', { name: 'Deployment' })).toBeNull()
    await userEvent.selectOptions(screen.getByLabelText('File field'), 'track')
    expect(
      screen.getByRole('option', { name: 'Track (Encounter)' }),
    ).toBeTruthy()
    expect(rules()).toEqual({ from_filename: { field: 'track', pattern: '' } })
    expect(problems()[0]).toMatch(/give every pattern/)
    await userEvent.type(screen.getByLabelText('Pattern'), 'site-(\\w+)_')
    expect(rules()).toEqual({
      from_filename: { field: 'track', pattern: 'site-(\\w+)_' },
    })
    expect(problems()).toEqual([])
  })

  it('asks the server what a file name gives and shows the answer', async () => {
    render(
      <Harness
        d={d}
        context={{ ...withFiles, type: 'integer' }}
        initial={{ from_filename: { field: 'audio', pattern: 'take_(\\d+)' } }}
      />,
    )
    const sample = screen.getByLabelText('Try a file name')
    await userEvent.type(sample, 'rec_take_07.wav')
    await waitFor(() =>
      expect(screen.getByTestId('tried')).toHaveTextContent('Gives 7'),
    )
    expect(previewFromFilename).toHaveBeenCalledWith({
      filename: 'rec_take_07.wav',
      patterns: ['take_(\\d+)'],
      kind: 'integer',
    })
    await userEvent.clear(sample)
    await userEvent.type(sample, 'rec.wav')
    await waitFor(() =>
      expect(screen.getByTestId('tried')).toHaveTextContent(/stay blank/),
    )
  })

  it("shows the server's problem with a pattern and blocks saving", async () => {
    render(
      <Harness
        d={d}
        context={{ ...withFiles, type: 'datetime' }}
        initial={{ from_filename: { field: 'audio', pattern: 'HHmmSS' } }}
      />,
    )
    await waitFor(() =>
      expect(problems()[0]).toMatch(/needs the tokens YYYY MM DD/),
    )
    const pattern = screen.getByLabelText('Pattern')
    await userEvent.clear(pattern)
    await userEvent.type(pattern, 'YYYYMMDD_HHmmSS')
    await waitFor(() => expect(problems()).toEqual([]))
    await userEvent.type(pattern, '(')
    await waitFor(() => expect(problems()[0]).toMatch(/regular expression/))
  })

  it('takes several patterns, tried in order, and stores one as a string', async () => {
    render(
      <Harness
        d={d}
        context={{ ...withFiles, type: 'datetime' }}
        initial={{
          from_filename: { field: 'audio', pattern: 'DDMMYYYY_HHmmSS' },
        }}
      />,
    )
    await userEvent.click(
      screen.getByRole('button', { name: 'Add another pattern' }),
    )
    // An empty row blocks saving until it is filled or removed.
    expect(problems()[0]).toMatch(/give every pattern/)
    await userEvent.type(screen.getByLabelText('Pattern 2'), 'YYYY-MM-DD')
    expect(rules()).toEqual({
      from_filename: {
        field: 'audio',
        pattern: ['DDMMYYYY_HHmmSS', 'YYYY-MM-DD'],
      },
    })
    expect(problems()).toEqual([])
    await userEvent.type(
      screen.getByLabelText('Try a file name'),
      'site_2024-03-15.csv',
    )
    await waitFor(() =>
      expect(screen.getByTestId('tried')).toHaveTextContent(
        'Gives 2024-03-15T00:00:00',
      ),
    )
    await userEvent.click(
      screen.getByRole('button', { name: 'Remove pattern 1' }),
    )
    expect(rules()).toEqual({
      from_filename: { field: 'audio', pattern: 'YYYY-MM-DD' },
    })
  })

  it('choosing no file field removes the rule', async () => {
    render(
      <Harness
        d={d}
        context={withFiles}
        initial={{ from_filename: { field: 'audio', pattern: '(.+)' } }}
      />,
    )
    await userEvent.selectOptions(screen.getByLabelText('File field'), '')
    expect(rules()).toEqual({})
    expect(problems()).toEqual([])
  })

  it('says when there is no file field to read', () => {
    render(<Harness d={d} />)
    expect(screen.getByText(/Add a file field/)).toBeTruthy()
    expect(screen.queryByLabelText('File field')).toBeNull()
  })
})
