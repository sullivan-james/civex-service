import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { schemasApi } from '../../api/schemas'
import { PatternFromExampleDialog } from './PatternFromExample'

// Stands in for the server, which is the one reader of patterns: a key regex
// is tried as JavaScript, a date format gives a canned value.
function renderDialog(
  props: Partial<Parameters<typeof PatternFromExampleDialog>[0]> = {},
) {
  const onApply = vi.fn()
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  render(
    <QueryClientProvider client={client}>
      <PatternFromExampleDialog
        kind="string"
        examples={[
          'sel_07_contour.csv',
          'sel_7_contour.csv',
          'sel_08_contour.csv',
        ]}
        dateStyle="token"
        onApply={onApply}
        onClose={() => {}}
        {...props}
      />
    </QueryClientProvider>,
  )
  return onApply
}

function select(part: string) {
  const input = screen.getByLabelText('Example file name') as HTMLInputElement
  const start = input.value.indexOf(part)
  input.setSelectionRange(start, start + part.length)
  fireEvent.select(input)
}

let preview: ReturnType<typeof vi.spyOn>
beforeEach(() => {
  preview = vi
    .spyOn(schemasApi, 'previewFromFilename')
    .mockImplementation(async ({ patterns, filenames = [] }) => {
      const [pattern] = patterns
      const results = filenames.map((filename) => {
        if (pattern.includes('YYYY')) {
          return {
            filename,
            value: filename.includes('2024') ? '2024-06-11T14:22:33' : null,
            error: null,
          }
        }
        const m = new RegExp(pattern).exec(filename)
        return { filename, value: m ? (m[1] ?? m[0]) : null, error: null }
      })
      return { problems: [null], value: null, error: null, results }
    })
})

describe('PatternFromExampleDialog', () => {
  it('writes the pattern from the marked part and shows every name', async () => {
    const onApply = renderDialog({ checkClashes: true })
    select('07')
    expect(screen.getByTestId('marked')).toHaveTextContent('07')
    await waitFor(() =>
      expect(screen.getByTestId('summary')).toHaveTextContent(
        '3 of 3 names give a value; 2 give the same key as another',
      ),
    )
    expect(preview).toHaveBeenLastCalledWith(
      expect.objectContaining({
        patterns: ['sel_([0-9]+)'],
        filenames: [
          'sel_07_contour.csv',
          'sel_7_contour.csv',
          'sel_08_contour.csv',
        ],
      }),
    )
    expect(screen.getAllByText(/— the same key as/)).toHaveLength(2)
    await userEvent.click(
      screen.getByRole('button', { name: 'Use this pattern' }),
    )
    expect(onApply).toHaveBeenCalledWith({ pattern: 'sel_([0-9]+)' })
  })

  it('gives a date as a capture and a format for the workflow action', async () => {
    const onApply = renderDialog({
      kind: 'datetime',
      dateStyle: 'separate',
      examples: ['rec_20240611-142233.wav'],
    })
    select('20240611-142233')
    expect(
      screen.getByText(/Reads as 11 June 2024 14:22:33 \(year first\)/),
    ).toBeTruthy()
    await waitFor(() =>
      expect(screen.getByTestId('summary')).toHaveTextContent(
        '1 of 1 names give a value',
      ),
    )
    await userEvent.click(
      screen.getByRole('button', { name: 'Use this pattern' }),
    )
    expect(onApply).toHaveBeenCalledWith({
      pattern: '([0-9]{8}[-_][0-9]{6})',
      dateFormat: 'YYYYMMDD[-_]HHmmSS',
    })
  })

  it('takes more names, pasted, without uploading anything', async () => {
    renderDialog({ examples: [] })
    expect(screen.getByText(/Add a file name or two/)).toBeTruthy()
    await userEvent.click(
      screen.getByRole('button', { name: /Add more file names/ }),
    )
    await userEvent.type(
      screen.getByLabelText('Or paste names, one per line'),
      'a_1.csv{enter}a_2.csv',
    )
    await userEvent.click(
      screen.getByRole('button', { name: 'Add these names' }),
    )
    expect(
      (screen.getByLabelText('Example file name') as HTMLInputElement).value,
    ).toBe('a_1.csv')
  })

  it('lets the pattern be written by hand', async () => {
    const onApply = renderDialog({ initialPattern: 'sel_(\\d+)' })
    await waitFor(() => expect(screen.getByTestId('summary')).toBeTruthy())
    await userEvent.click(
      screen.getByRole('button', { name: 'Use this pattern' }),
    )
    expect(onApply).toHaveBeenCalledWith({ pattern: 'sel_(\\d+)' })
  })
})
