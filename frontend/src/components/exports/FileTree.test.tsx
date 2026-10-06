import { describe, it, expect } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { pathsToRows } from '../../utils/fileTree'
import { FilePreviewList } from './FilePreviewList'
import { FileTree } from './FileTree'
import { plan } from '../files/testSupport'

const rows = pathsToRows([
  { path: 'Parent 1/Child 1/a.txt', size: 2048 },
  { path: 'Parent 1/Child 1/b.txt', size: 10 },
  { path: 'Parent 1/notes.txt', size: 5 },
  { path: 'Parent 2/c.txt', size: 7, available: false },
])

describe('a folder tree', () => {
  it('shows folders and files, indented by level', () => {
    render(<FileTree rows={rows} label="Tree" collapsible />)

    const tree = screen.getByLabelText('Tree')
    expect(within(tree).getAllByRole('listitem')).toHaveLength(7)
    expect(within(tree).getByText('Child 1')).toBeTruthy()
    const deep = within(tree).getByText('a.txt').closest('li')!
    const top = within(tree).getByText('Parent 1').closest('li')!
    expect(parseInt(deep.style.paddingLeft)).toBeGreaterThan(
      parseInt(top.style.paddingLeft || '0'),
    )
  })

  it('says how many files a folder holds and how big a file is', () => {
    render(<FileTree rows={rows} label="Tree" collapsible />)

    const parent = screen.getByRole('button', { name: /parent 1/i })
    expect(within(parent).getByText('3')).toBeTruthy()
    expect(screen.getByText('2.0 KB')).toBeTruthy()
  })

  it('closes and opens a folder on click', async () => {
    render(<FileTree rows={rows} label="Tree" collapsible />)
    const parent = screen.getByRole('button', { name: /parent 1/i })
    expect(parent.getAttribute('aria-expanded')).toBe('true')

    await userEvent.click(parent)

    expect(parent.getAttribute('aria-expanded')).toBe('false')
    expect(screen.queryByText('Child 1')).toBeNull()
    expect(screen.queryByText('a.txt')).toBeNull()
    expect(screen.getByText('Parent 2')).toBeTruthy() // its sibling is untouched
    await userEvent.click(parent)
    expect(screen.getByText('a.txt')).toBeTruthy()
  })

  it('closes just one folder, leaving the others open', async () => {
    render(<FileTree rows={rows} label="Tree" collapsible />)

    await userEvent.click(screen.getByRole('button', { name: /child 1/i }))

    expect(screen.queryByText('a.txt')).toBeNull()
    expect(screen.getByText('notes.txt')).toBeTruthy()
    expect(screen.getByText('c.txt')).toBeTruthy()
  })

  it('marks a file that cannot be reached', () => {
    render(<FileTree rows={rows} label="Tree" collapsible />)

    const gone = screen.getByText('c.txt').closest('div')!

    expect(gone.className).toMatch(/line-through/)
    expect(gone.getAttribute('title')).toMatch(/can’t be reached/i)
  })

  it('is just a picture when not collapsible: nothing to click', () => {
    render(<FileTree rows={rows} label="Tree" />)

    expect(screen.queryByRole('button')).toBeNull()
    expect(screen.getByText('Parent 1')).toBeTruthy()
  })
})

describe('the preview of an export', () => {
  const data = {
    ...plan({ total: 5, available: 5 }),
    items: [
      {
        path: 'Study/Day 1/a.contour',
        size: 1,
        available: true,
        volume: 'default',
      },
      {
        path: 'Study/Day 2/b.contour',
        size: 1,
        available: true,
        volume: 'default',
      },
    ],
  }

  it('is a navigable folder tree, not a list of paths', async () => {
    render(<FilePreviewList data={data} />)

    const tree = screen.getByLabelText('Folder preview')
    expect(within(tree).getByRole('button', { name: /study/i })).toBeTruthy()
    expect(within(tree).queryByText('Study/Day 1/a.contour')).toBeNull()

    await userEvent.click(within(tree).getByRole('button', { name: /day 1/i }))

    expect(within(tree).queryByText('a.contour')).toBeNull()
    expect(within(tree).getByText('b.contour')).toBeTruthy()
  })

  it('says how many more files there are than it shows', () => {
    render(<FilePreviewList data={data} />)

    expect(screen.getByText(/and 3 more files/i)).toBeTruthy()
  })

  it('says when there is nothing to export', () => {
    render(<FilePreviewList data={{ ...data, total: 0, items: [] }} />)

    expect(screen.getByText(/nothing to export/i)).toBeTruthy()
    expect(screen.queryByLabelText('Folder preview')).toBeNull()
  })
})
