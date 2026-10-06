import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { FilePreview } from '../../api/fileAccess'
import { FilePreviewList } from './FilePreviewList'

const preview = (over: Partial<FilePreview> = {}): FilePreview =>
  ({
    total: 2,
    available: 2,
    bytes: 2048,
    available_bytes: 2048,
    complete: true,
    scattered: false,
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

    expect(
      screen.getByText(/2 files \(2\.0 KB\) · 1 table on default \(2\)/),
    ).toBeTruthy()
    expect(screen.getByText('1 row')).toBeTruthy()
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

  it('says what cannot be reached and what is on several drives', () => {
    render(
      <FilePreviewList data={preview({ available: 1, scattered: true })} />,
    )

    expect(screen.getByText(/1 file can’t be reached right now/)).toBeTruthy()
    expect(screen.getByText(/several drives/)).toBeTruthy()
  })

  it('never breaks on an answer missing parts', () => {
    render(<FilePreviewList data={{} as FilePreview} />)

    expect(screen.getByText(/nothing to export/i)).toBeTruthy()
  })
})
