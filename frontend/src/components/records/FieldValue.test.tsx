import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { FieldValue } from './FieldValue'
import { CollectionTimeZone } from './CollectionTimeZone'
import type { Field } from '../../api/schemas'

const field = (extra: Partial<Field> = {}): Field => ({
  id: 'f',
  name: 't',
  label: null,
  type: 'datetime',
  required: false,
  restrictions: {},
  default: null,
  position: 0,
  ...extra,
})

describe('FieldValue datetime', () => {
  it('renders wall time in the collection zone with the UTC value on hover', () => {
    render(
      <CollectionTimeZone timeZone="America/Chicago">
        <FieldValue value="2024-03-01T21:30:00+00:00" field={field()} />
      </CollectionTimeZone>,
    )
    const el = screen.getByText(/3:30 PM CST/)
    expect(el).toHaveAttribute('title', '2024-03-01T21:30:00+00:00')
  })

  it("prefers the field's own zone", () => {
    render(
      <CollectionTimeZone timeZone="America/Chicago">
        <FieldValue
          value="2024-03-01T06:30:00+00:00"
          field={field({ restrictions: { timezone: 'Asia/Kolkata' } })}
        />
      </CollectionTimeZone>,
    )
    expect(screen.getByText(/12:00 PM/)).toBeInTheDocument()
  })

  it('reads an offset-less stored value as UTC', () => {
    render(
      <CollectionTimeZone timeZone="UTC">
        <FieldValue value="2024-03-01T15:30:00" field={field()} />
      </CollectionTimeZone>,
    )
    expect(screen.getByText(/3:30 PM UTC/)).toBeInTheDocument()
  })

  it('leaves non-datetime strings alone', () => {
    render(
      <FieldValue
        value="2024-03-01T21:30:00+00:00"
        field={field({ type: 'string' })}
      />,
    )
    expect(screen.getByText('2024-03-01T21:30:00+00:00')).toBeInTheDocument()
  })
})
