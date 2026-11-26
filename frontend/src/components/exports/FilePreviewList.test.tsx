import { render as rtlRender, screen, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactElement } from 'react'
import { describe, expect, it } from 'vitest'
import type { FilePreview } from '../../api/fileAccess'
import { FilePreviewList } from './FilePreviewList'

// The components read what the server offers (a query), so they need a client.
const render = (ui: ReactElement) =>
  rtlRender(
    <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>,
  )

const preview = (over: Partial<FilePreview> = {}): FilePreview =>
  ({
    total: 2,
    available: 2,
    bytes: 2048,
    available_bytes: 2048,
    complete: true,
    link_volume: 'default',
    by_volume: [{ volume: 'default', files: 2, bytes: 2048 }],
    summary: '',
    unavailable: [],
    tables: [],
    items: [
      { path: 'A/s1/s1.txt', size: 1024, available: true, volume: 'default' },
      { path: 'B/s2/s2.txt', size: 1024, available: true, volume: 'default' },
    ],
    ...over,
  }) as unknown as FilePreview

const table = (path: string, rows: number) => ({
  name: path.split('/').pop()!,
  folder: path.split('/').slice(0, -1).join('/'),
  path,
  kind: 'selection',
  rows,
  columns: ['id'],
  format: 'csv' as const,
  shape: 'rows' as const,
})

describe('the preview of what an export makes', () => {
  it('is one folder tree, with each table in the folder it will be written in', () => {
    render(
      <FilePreviewList
        data={preview({
          tables: [table('A/Selections.csv', 2), table('Recordings.csv', 3)],
        })}
      />,
    )

    const tree = screen.getByRole('list', { name: 'Folder preview' })
    expect(within(tree).getByText('Recordings.csv')).toBeTruthy()
    expect(within(tree).getByText('3 rows')).toBeTruthy()
    expect(within(tree).getByText('Selections.csv')).toBeTruthy()
    expect(within(tree).getByText('2 rows')).toBeTruthy()
    expect(within(tree).getByText('s1.txt')).toBeTruthy()
    // One tree: there is no separate list of tables to cross-check.
    expect(screen.queryByRole('list', { name: 'Tables' })).toBeNull()
  })

  it('says how many files, how big, and how many tables', () => {
    render(<FilePreviewList data={preview({ tables: [table('T.csv', 1)] })} />)

    expect(screen.getByText(/2 files \(2\.0 KB\) · 1 table\./)).toBeTruthy()
    expect(screen.getByText('1 row')).toBeTruthy()
  })

  it('says first which files are downloaded from the server, not that they are lost', () => {
    render(
      <FilePreviewList
        data={preview({
          total: 3,
          available: 1,
          to_fetch: { files: 2, bytes: 2 * 1024 * 1024 },
        })}
      />,
    )
    expect(
      screen.getByText(
        /2 files \(2.0 MB\) aren't on this computer yet: they are downloaded from the server first/,
      ),
    ).toBeInTheDocument()
    expect(screen.queryByText(/can’t be reached/)).not.toBeInTheDocument()
  })

  it('shows tables alone when there are no files', () => {
    render(
      <FilePreviewList
        data={preview({
          total: 0,
          available: 0,
          bytes: 0,
          by_volume: [],
          items: [],
          tables: [table('Selections.csv', 4)],
        })}
      />,
    )

    expect(screen.getByText('Selections.csv')).toBeTruthy()
    expect(screen.queryByText(/nothing to export/i)).toBeNull()
  })

  it('says so when there is nothing', () => {
    render(
      <FilePreviewList
        data={preview({ total: 0, available: 0, items: [], by_volume: [] })}
      />,
    )

    expect(screen.getByText(/nothing to export/i)).toBeTruthy()
  })

  it('says what cannot be reached, on which drive and what to do, before anything is made', () => {
    render(
      <FilePreviewList
        data={preview({
          available: 1,
          unavailable: [
            {
              volume: 'archive',
              state: 'offline',
              reason: 'Drive “archive” is not connected.',
              fix: 'Plug in the drive called archive.',
              files: 1,
              bytes: 1024,
              records: ['Selection 2'],
            },
          ],
        } as Partial<FilePreview>)}
      />,
    )

    expect(screen.getByText(/1 file can’t be reached right now/)).toBeTruthy()
    expect(screen.getByText(/on “archive”/)).toBeTruthy()
    expect(screen.getByText(/plug in the drive called archive/i)).toBeTruthy()
  })

  it('never breaks on an answer missing parts', () => {
    render(<FilePreviewList data={{} as FilePreview} />)

    expect(screen.getByText(/nothing to export/i)).toBeTruthy()
  })
})
