import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RecordFieldGrid, restrictionHints } from './RecordFieldGrid'
import type { Field } from '../../api/schemas'

const field = (
  name: string,
  type: string,
  label: string | null = null,
  restrictions: Record<string, unknown> = {},
): Field =>
  ({
    id: name,
    name,
    label,
    type,
    required: false,
    restrictions,
    default: null,
    position: 0,
  }) as unknown as Field

const audio = field('audio', 'file', 'Audio')
const start = field('start', 'datetime', 'Start', {
  from_filename: { field: 'audio', pattern: 'YYYYMMDD_HHmmSS' },
})

describe('a field filled from a file name', () => {
  it('is hinted with the file field it is read from, by its label', () => {
    expect(restrictionHints(start, [audio, start])).toEqual([
      "filled from Audio's name",
    ])
    // Without the record's fields, the file field's name has to do.
    expect(restrictionHints(start)).toEqual(["filled from audio's name"])
  })

  it('shows the hint on the record form', () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <RecordFieldGrid
            fields={[audio, start]}
            data={{}}
            onSave={vi.fn()}
            readOnly="just looking"
          />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    expect(screen.getByText("filled from Audio's name")).toBeTruthy()
  })
})
