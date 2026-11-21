import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RecordFieldGrid } from './RecordFieldGrid'
import type { Field } from '../../api/schemas'

const field = (
  name: string,
  type: string,
  restrictions: Record<string, unknown> = {},
): Field =>
  ({
    id: name,
    name,
    label: null,
    type,
    required: false,
    restrictions,
    default: null,
    position: 0,
  }) as unknown as Field

const mass = field('mass', 'float')
const bmi = field('bmi', 'formula', {
  expression: 'mass / height ** 2',
  result: 'float',
  unit: 'kg/m²',
})

function grid(computed?: Parameters<typeof RecordFieldGrid>[0]['computed']) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <RecordFieldGrid
          fields={[mass, bmi]}
          data={{ mass: 81 }}
          onSave={vi.fn()}
          computed={computed}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('a formula field on a record', () => {
  it('shows what it works out to, as the type it gives, and is not editable', () => {
    grid({ values: { bmi: 25 } })
    expect(screen.getByText('25')).toBeInTheDocument()
    expect(screen.getByText('kg/m²')).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /bmi/i }),
    ).not.toBeInTheDocument()
  })

  it('says why it is blank', () => {
    grid({ values: { bmi: null }, errors: { bmi: 'divided by zero' } })
    expect(screen.getByText('Blank: divided by zero')).toBeInTheDocument()
  })

  it('on a record not added yet, says when it is worked out', () => {
    grid()
    expect(
      screen.getByText('Worked out once the record is added'),
    ).toBeInTheDocument()
  })
})
