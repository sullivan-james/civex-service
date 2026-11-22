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
  it('is not explained on the record: it reads like any other field', () => {
    expect(restrictionHints(start)).toEqual([])
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
    expect(screen.queryByText(/Filled from/)).toBeNull()
  })
})
