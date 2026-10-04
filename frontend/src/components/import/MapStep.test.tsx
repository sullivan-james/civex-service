import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MapStep } from './MapStep'
import { initialMapState, SKIP_COLUMN } from './importWizardTypes'
import type { Field } from '../../api/schemas'

const fields: Field[] = ['weight', 'site'].map((name, i) => ({
  id: `f${i}`,
  name,
  label: null,
  type: 'string',
  required: false,
  restrictions: {},
  default: null,
  position: i,
}))

function renderCsvStep(
  over: Partial<React.ComponentProps<typeof MapStep>> = {},
) {
  const props: React.ComponentProps<typeof MapStep> = {
    mode: 'csv',
    state: initialMapState(),
    onChange: vi.fn(),
    showSchemaPicker: false,
    schemas: [],
    isNewSchema: false,
    onSchemaChoiceChange: vi.fn(),
    availableFields: fields,
    availableFileFields: [],
    availableNonFileFields: fields,
    targetSchemaName: 'sample',
    needsParent: false,
    parentSchema: null,
    hasParentCandidates: false,
    parsedCsv: { columns: ['wt', 'loc'], rows: [] },
    canMatch: false,
    strategy: 'create',
    filenames: [],
    extraOutputType: 'string',
    mapValid: true,
    onBack: vi.fn(),
    onContinue: vi.fn(),
    ...over,
  }
  render(<MapStep {...props} />)
  return props
}

describe('MapStep (csv)', () => {
  it('lists every CSV column defaulting to skip', () => {
    renderCsvStep()
    const selects = screen.getAllByRole('combobox')
    expect(selects).toHaveLength(2)
    selects.forEach((s) => expect(s).toHaveValue(SKIP_COLUMN))
  })

  it('patches columnMap when a column is mapped to a field', async () => {
    const props = renderCsvStep()
    await userEvent.selectOptions(screen.getAllByRole('combobox')[0], 'weight')
    expect(props.onChange).toHaveBeenCalledWith({
      columnMap: { wt: 'weight' },
    })
  })

  it('disables Continue when the mapping is invalid', () => {
    renderCsvStep({ mapValid: false })
    expect(screen.getByRole('button', { name: /continue/i })).toBeDisabled()
  })

  it('wires Back and Continue', async () => {
    const props = renderCsvStep()
    await userEvent.click(screen.getByRole('button', { name: /back/i }))
    await userEvent.click(screen.getByRole('button', { name: /continue/i }))
    expect(props.onBack).toHaveBeenCalled()
    expect(props.onContinue).toHaveBeenCalled()
  })
})

describe('MapStep timezone hint', () => {
  const datetimeField = {
    ...fields[0],
    id: 'f9',
    name: 'taken_at',
    type: 'datetime',
  }
  const mapped = {
    ...initialMapState(),
    columnMap: { wt: 'taken_at' },
  }
  const base = {
    availableFields: [...fields, datetimeField],
    state: mapped,
  }

  async function hint() {
    await userEvent.click(
      screen.getByRole('button', { name: 'More information' }),
    )
    return screen.getByRole('tooltip')
  }

  it('says which zone times are read in when the collection has one', async () => {
    renderCsvStep({ ...base, collectionTimeZone: 'America/Chicago' })
    expect(await hint()).toHaveTextContent(/read as America\/Chicago/)
  })

  it('warns that an unset collection reads times as UTC', async () => {
    renderCsvStep({ ...base, collectionTimeZone: null })
    expect(await hint()).toHaveTextContent(
      /no timezone, so times .* read as UTC/,
    )
  })

  it("defers to the chosen collection when it isn't picked yet", async () => {
    renderCsvStep({ ...base, collectionTimeZone: undefined })
    expect(await hint()).toHaveTextContent(/chosen collection's timezone/)
  })

  it('offers no hint when no column maps to a datetime field', () => {
    renderCsvStep({ collectionTimeZone: 'America/Chicago' })
    expect(
      screen.queryByRole('button', { name: 'More information' }),
    ).toBeNull()
  })
})
