import { describe, it, expect, vi } from 'vitest'
import { useCallback, useState } from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
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
    await userEvent.type(screen.getByLabelText('Download file name'), '_clip.')
    await userEvent.click(screen.getByRole('button', { name: '{ext}' }))
    expect(rules()).toEqual({ filename_template: '{deployment_id}_clip.{ext}' })
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
