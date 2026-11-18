import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
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

const PLACE_2 = '^(?:[^ ._-]+[ ._-]+){1}([0-9]+)'

/** Click a part of the example name; with `through`, Shift+click another. */
async function pick(part: string, through?: string) {
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: part }))
  if (through) {
    await user.keyboard('{Shift>}')
    await user.click(screen.getByRole('button', { name: through }))
    await user.keyboard('{/Shift}')
  }
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
  it('takes the part clicked by its place and shows every name', async () => {
    const onApply = renderDialog({ checkClashes: true })
    await pick('07')
    await waitFor(() =>
      expect(screen.getByTestId('summary')).toHaveTextContent(
        '3 of 3 names give a value; 2 give the same key as another',
      ),
    )
    expect(preview).toHaveBeenCalledWith(
      expect.objectContaining({
        patterns: [PLACE_2],
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
    expect(onApply).toHaveBeenCalledWith({ pattern: PLACE_2 })
  })

  it('finds it by the word before it when that reads more names', async () => {
    const onApply = renderDialog({
      examples: ['20240611_dive07_a.wav', 'extra_20240612_dive163_b.wav'],
    })
    await pick('dive07')
    // The number inside is what is meant; by its place, the second name
    // would give 20240612.
    await waitFor(() =>
      expect(
        screen.getByRole('radio', { name: /What comes before it: “dive”/ }),
      ).toBeChecked(),
    )
    await waitFor(() =>
      expect(screen.getByTestId('summary')).toHaveTextContent('2 of 2'),
    )
    expect(await screen.findByText('163')).toBeTruthy()
    await userEvent.click(
      screen.getByRole('button', { name: 'Use this pattern' }),
    )
    expect(onApply).toHaveBeenCalledWith({ pattern: 'dive([0-9]+)' })
  })

  it('gives a date as a capture and a format for the workflow action', async () => {
    const onApply = renderDialog({
      kind: 'datetime',
      dateStyle: 'separate',
      examples: ['rec_20240611-142233.wav'],
    })
    await pick('20240611', '142233')
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
    expect(screen.getByRole('button', { name: 'a' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'csv' })).toBeTruthy()
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
