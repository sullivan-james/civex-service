import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useState } from 'react'
import { DateInput, DateTimeInput } from './DateInput'
import { setDateFormat } from '../../utils/dateFormat'

afterEach(() => localStorage.clear())

/** A form field holding what the input sends, as a caller would. */
function Holder({
  initial = '',
  onValue,
  precision,
  time = false,
}: {
  initial?: string
  onValue: (v: string) => void
  precision?: 'year' | 'month' | 'day'
  time?: boolean
}) {
  const [value, setValue] = useState(initial)
  const change = (v: string) => {
    setValue(v)
    onValue(v)
  }
  return time ? (
    <DateTimeInput aria-label="When" value={value} onChange={change} />
  ) : (
    <DateInput
      aria-label="When"
      value={value}
      onChange={change}
      precision={precision}
    />
  )
}

function typeInto(text: string) {
  const input = screen.getByLabelText('When')
  fireEvent.change(input, { target: { value: text } })
  return input
}

describe('DateInput', () => {
  it('shows a stored date in the chosen pattern', () => {
    render(<Holder initial="2019-06-14" onValue={() => {}} />)
    expect(screen.getByLabelText('When')).toHaveValue('14/06/2019')
  })

  it.each([
    ['DD/MM/YYYY', '14/06/2019'],
    ['MM/DD/YYYY', '06/14/2019'],
    ['YYYY-MM-DD', '2019-06-14'],
    ['D MMM YYYY', '14 Jun 2019'],
  ] as const)('reads %s as typed and sends the stored form', (format, text) => {
    setDateFormat(format)
    const onValue = vi.fn()
    render(<Holder onValue={onValue} />)
    typeInto(text)
    expect(onValue).toHaveBeenLastCalledWith('2019-06-14')
  })

  it('keeps every keystroke while typing', async () => {
    const onValue = vi.fn()
    render(<Holder onValue={onValue} />)
    const input = screen.getByLabelText('When')
    await userEvent.type(input, '4/6/2019')
    expect(input).toHaveValue('4/6/2019')
    expect(onValue).toHaveBeenLastCalledWith('2019-06-04')
  })

  it('sends text that is not a date as typed, and says so', () => {
    const onValue = vi.fn()
    render(<Holder onValue={onValue} />)
    const input = typeInto('31/02/2019')
    expect(onValue).toHaveBeenLastCalledWith('31/02/2019')
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Not a date. Use DD/MM/YYYY.',
    )
  })

  it('sends empty for empty', () => {
    const onValue = vi.fn()
    render(<Holder initial="2019-06-14" onValue={onValue} />)
    typeInto('')
    expect(onValue).toHaveBeenLastCalledWith('')
  })

  it('takes a month or a year only where the field allows it', () => {
    const onValue = vi.fn()
    const { unmount } = render(<Holder onValue={onValue} precision="month" />)
    typeInto('06/2019')
    expect(onValue).toHaveBeenLastCalledWith('2019-06')
    typeInto('2019')
    expect(onValue).toHaveBeenLastCalledWith('2019')
    expect(screen.getByRole('alert')).toBeInTheDocument()
    unmount()

    render(<Holder onValue={onValue} precision="day" />)
    typeInto('06/2019')
    expect(onValue).toHaveBeenLastCalledWith('06/2019')
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })

  it('shows a partial date at its own precision', () => {
    render(<Holder initial="2019-06" precision="year" onValue={() => {}} />)
    expect(screen.getByLabelText('When')).toHaveValue('06/2019')
  })

  it('shows the date again in another pattern when the setting changes', () => {
    render(<Holder initial="2019-06-14" onValue={() => {}} />)
    act(() => setDateFormat('D MMM YYYY'))
    expect(screen.getByLabelText('When')).toHaveValue('14 Jun 2019')
  })

  it('takes a date picked from the calendar', () => {
    const onValue = vi.fn()
    const { container } = render(<Holder onValue={onValue} />)
    const picker = container.querySelector('input[type=date]')!
    fireEvent.change(picker, { target: { value: '2019-06-14' } })
    expect(onValue).toHaveBeenLastCalledWith('2019-06-14')
    expect(screen.getByLabelText('When')).toHaveValue('14/06/2019')
  })
})

describe('DateTimeInput', () => {
  it('shows wall time in the chosen pattern', () => {
    render(<Holder time initial="2024-03-01T15:30:45" onValue={() => {}} />)
    expect(screen.getByLabelText('When')).toHaveValue('01/03/2024 15:30:45')
  })

  it('reads a date and 24-hour time and sends wall time', () => {
    const onValue = vi.fn()
    render(<Holder time onValue={onValue} />)
    typeInto('01/03/2024 15:30')
    expect(onValue).toHaveBeenLastCalledWith('2024-03-01T15:30')
    typeInto('01/03/2024 15:30:07')
    expect(onValue).toHaveBeenLastCalledWith('2024-03-01T15:30:07')
  })

  it('refuses a date with no time', () => {
    const onValue = vi.fn()
    render(<Holder time onValue={onValue} />)
    typeInto('01/03/2024')
    expect(onValue).toHaveBeenLastCalledWith('01/03/2024')
    expect(screen.getByRole('alert')).toHaveTextContent('DD/MM/YYYY HH:MM')
  })

  it('keeps typing when the caller drops zero seconds on the way back', () => {
    // A caller that stores UTC and shows it back drops `:00`.
    function RoundTrip() {
      const [value, setValue] = useState('')
      return (
        <DateTimeInput
          aria-label="When"
          value={value}
          onChange={(v) => setValue(v.replace(/:00$/, ''))}
        />
      )
    }
    render(<RoundTrip />)
    const input = typeInto('01/03/2024 15:30:00')
    expect(input).toHaveValue('01/03/2024 15:30:00')
  })
})
