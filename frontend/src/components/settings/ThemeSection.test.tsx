import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeAll, describe, expect, it } from 'vitest'
import ThemeSection from './ThemeSection'
import { ThemeProvider } from '../../hooks/useTheme'
import { useDateFormat } from '../../hooks/useDateFormat'
import { formatDate } from '../../utils/dates'

beforeAll(() => {
  window.matchMedia ??= ((query: string) => ({
    matches: false,
    media: query,
    addEventListener() {},
    removeEventListener() {},
  })) as unknown as typeof window.matchMedia
})

afterEach(() => localStorage.clear())

/** A date shown by a component that doesn't read the setting itself. */
function SomeDate() {
  return <p data-testid="date">{formatDate('2019-06-14')}</p>
}

/** Like `App`: reads the setting, so every page below re-renders. */
function Root() {
  useDateFormat()
  return (
    <>
      <ThemeSection />
      <SomeDate />
    </>
  )
}

describe('Date format setting', () => {
  it('starts on DD/MM/YYYY with today as an example', () => {
    render(
      <ThemeProvider>
        <Root />
      </ThemeProvider>,
    )
    expect(screen.getByLabelText('Date format')).toHaveValue('DD/MM/YYYY')
    expect(screen.getByText(/^Today: \d{2}\/\d{2}\/\d{4} \d{2}:\d{2}$/))
    expect(screen.getByTestId('date')).toHaveTextContent('14/06/2019')
  })

  it('changes every date at once and is kept in the browser', async () => {
    render(
      <ThemeProvider>
        <Root />
      </ThemeProvider>,
    )
    await userEvent.selectOptions(
      screen.getByLabelText('Date format'),
      'D MMM YYYY',
    )
    expect(screen.getByTestId('date')).toHaveTextContent('14 Jun 2019')
    expect(screen.getByText(/^Today: \d{1,2} [A-Z][a-z]{2} \d{4} /))
    expect(localStorage.getItem('civex-date-format')).toBe('D MMM YYYY')
  })

  it('opens on the stored choice', () => {
    localStorage.setItem('civex-date-format', 'YYYY-MM-DD')
    render(
      <ThemeProvider>
        <Root />
      </ThemeProvider>,
    )
    expect(screen.getByLabelText('Date format')).toHaveValue('YYYY-MM-DD')
    expect(screen.getByTestId('date')).toHaveTextContent('2019-06-14')
  })
})
