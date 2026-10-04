import { describe, it, expect, vi } from 'vitest'
import { useState } from 'react'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DynamicField } from './DynamicField'
import type { Field } from '../../api/schemas'

// The map canvas can't run in jsdom; the editor's own tests cover its behaviour.
vi.mock('../geo/GeoMap', () => ({ default: () => <div data-testid="map" /> }))

function field(
  type: string,
  restrictions: Record<string, unknown> = {},
): Field {
  return {
    id: 'f',
    name: 'f',
    label: null,
    type,
    required: false,
    restrictions,
    default: null,
    position: 0,
  }
}

function Harness({ f, initial = '' }: { f: Field; initial?: unknown }) {
  const [value, setValue] = useState<unknown>(initial)
  return (
    <>
      <DynamicField field={f} value={value} onChange={setValue} id="input" />
      <output data-testid="value">{JSON.stringify(value)}</output>
    </>
  )
}

const value = () => JSON.parse(screen.getByTestId('value').textContent!)

describe('location input guidance', () => {
  it('shows the format as a placeholder and the other ways in a tooltip', async () => {
    render(<Harness f={field('geo')} />)
    expect(screen.getByRole('textbox')).toHaveAttribute(
      'placeholder',
      expect.stringContaining('latitude, longitude'),
    )
    await userEvent.click(
      screen.getByRole('button', { name: 'Other ways to enter a location' }),
    )
    const tip = screen.getByRole('tooltip')
    expect(tip).toHaveTextContent(/south and west are negative/)
    expect(tip).toHaveTextContent(/POINT\(-3.41 56.12\)/)
  })

  it('says how it read what you typed', async () => {
    render(<Harness f={field('geo')} />)
    await userEvent.type(screen.getByRole('textbox'), '56.12, -3.41')
    expect(screen.getByText('Reads as 56.12° N, 3.41° W.')).toBeInTheDocument()
    expect(value()).toEqual({ type: 'Point', coordinates: [-3.41, 56.12] })
    expect(screen.getByRole('img', { name: /marked/ })).toBeInTheDocument()
  })

  it('explains an unreadable entry', async () => {
    render(<Harness f={field('geo')} />)
    await userEvent.type(screen.getByRole('textbox'), 'near the harbour')
    expect(screen.getByRole('alert')).toHaveTextContent(
      /Couldn't read that as a location/,
    )
  })

  it('lists the field rules and warns when a point breaks them', async () => {
    render(
      <Harness
        f={field('geo', { geometry_types: ['Point'], bbox: [-12, 48, 4, 62] })}
      />,
    )
    expect(
      screen.getByText(/Allowed: Point, within 48° N to 62° N, 12° W to 4° E/),
    ).toBeInTheDocument()
    // the allowed area is drawn even before anything is typed
    expect(
      screen.getByRole('img', { name: /Allowed area/ }),
    ).toBeInTheDocument()
    await userEvent.type(screen.getByRole('textbox'), '63.4, -20.1')
    expect(screen.getByRole('alert')).toHaveTextContent(
      /outside the allowed area/,
    )
  })

  it('warns about the wrong shape', async () => {
    render(<Harness f={field('geo', { geometry_types: ['Polygon'] })} />)
    await userEvent.type(screen.getByRole('textbox'), '56, -3')
    expect(screen.getByRole('alert')).toHaveTextContent(
      /takes Polygon, not Point/,
    )
  })
})

describe('unit and partial date guidance', () => {
  it('explains that a unit can be typed and converts it', async () => {
    render(<Harness f={field('float', { unit: 'm' })} />)
    await userEvent.click(
      screen.getByRole('button', { name: 'More information' }),
    )
    expect(screen.getByRole('tooltip')).toHaveTextContent(
      /Stored in m\. You can also type a value with its unit, such as 1024 ft/,
    )
    await userEvent.type(screen.getByRole('textbox'), '1024 ft')
    expect(screen.getByText('= 312.1152 m')).toBeInTheDocument()
    expect(value()).toBe('312.1152')
  })

  it('explains what a partial date accepts', () => {
    render(<Harness f={field('date', { precision: 'month' })} />)
    expect(screen.getByRole('textbox')).toHaveAttribute(
      'title',
      expect.stringMatching(
        /A month or a full date works; a bare year does not/,
      ),
    )
  })
})

describe('location map editor from the record form', () => {
  it('opens the editor, and applying puts the location into the field', async () => {
    render(<Harness f={field('geo')} />)
    await userEvent.click(screen.getByRole('button', { name: 'Edit on map…' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(
      within(dialog).getByLabelText('Or paste coordinates'),
      '56.12N 3.41W',
    )
    await userEvent.click(within(dialog).getByRole('button', { name: 'Apply' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(value()).toEqual({ type: 'Point', coordinates: [-3.41, 56.12] })
    expect(screen.getByRole('textbox')).toHaveValue('56.12, -3.41')
  })

  it('cancelling leaves the field alone', async () => {
    render(
      <Harness
        f={field('geo')}
        initial={{ type: 'Point', coordinates: [1, 2] }}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Edit on map…' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(
      within(dialog).getByRole('button', { name: 'Cancel' }),
    )
    expect(value()).toEqual({ type: 'Point', coordinates: [1, 2] })
  })
})
