import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DynamicField } from './DynamicField'
import type { Field } from '../../api/schemas'

function makeField(overrides: Partial<Field>): Field {
  return {
    id: 'f1',
    name: 'f',
    label: null,
    type: 'string',
    required: false,
    restrictions: {},
    default: null,
    position: 0,
    ...overrides,
  }
}

describe('DynamicField', () => {
  it('renders a select for string fields with choices', async () => {
    const onChange = vi.fn()
    render(
      <DynamicField
        field={makeField({
          type: 'string',
          restrictions: { choices: ['red', 'green'] },
        })}
        value=""
        onChange={onChange}
        id="x"
      />,
    )
    const select = screen.getByRole('combobox')
    await userEvent.selectOptions(select, 'green')
    expect(onChange).toHaveBeenCalledWith('green')
  })

  it('applies min/max restrictions to integer inputs', () => {
    render(
      <DynamicField
        field={makeField({
          type: 'integer',
          restrictions: { min: 1, max: 9 },
        })}
        value="3"
        onChange={() => {}}
      />,
    )
    const input = screen.getByRole('spinbutton')
    expect(input).toHaveAttribute('min', '1')
    expect(input).toHaveAttribute('max', '9')
    expect(input).toHaveAttribute('step', '1')
  })

  it('marks required inputs as required', () => {
    render(
      <DynamicField
        field={makeField({ type: 'float', required: true })}
        value=""
        onChange={() => {}}
      />,
    )
    const input = screen.getByRole('spinbutton')
    expect(input).toBeRequired()
    expect(input).toHaveAttribute('aria-required', 'true')
  })

  it('emits a boolean from the checkbox', async () => {
    const onChange = vi.fn()
    render(
      <DynamicField
        field={makeField({ type: 'boolean' })}
        value={false}
        onChange={onChange}
      />,
    )
    await userEvent.click(screen.getByRole('checkbox'))
    expect(onChange).toHaveBeenCalledWith(true)
  })

  it('splits comma-separated tags into a trimmed list', () => {
    const onChange = vi.fn()
    render(
      <DynamicField
        field={makeField({ type: 'tags' })}
        value={[]}
        onChange={onChange}
      />,
    )
    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'a, b ,, c' },
    })
    expect(onChange).toHaveBeenLastCalledWith(['a', 'b', 'c'])
  })

  it('passes aria-invalid through to the control', () => {
    render(
      <DynamicField
        field={makeField({ type: 'url' })}
        value=""
        onChange={() => {}}
        aria-invalid
      />,
    )
    expect(screen.getByRole('textbox')).toHaveAttribute('aria-invalid', 'true')
  })
})
