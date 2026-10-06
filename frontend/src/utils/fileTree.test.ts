import { describe, it, expect } from 'vitest'
import { pathsToRows, visibleRows } from './fileTree'

const names = (paths: string[]) =>
  pathsToRows(paths.map((path) => ({ path }))).map(
    (r) => `${'  '.repeat(r.depth)}${r.name}${r.kind === 'folder' ? '/' : ''}`,
  )

describe('paths as a folder tree', () => {
  it('nests folders, with folders before files at each level', () => {
    expect(
      names([
        'Study 1/Day 1/b.txt',
        'Study 1/Day 1/a.txt',
        'Study 1/notes.txt',
        'Study 1/Day 2/c.txt',
        'readme.txt',
      ]),
    ).toEqual([
      'Study 1/',
      '  Day 1/',
      '    a.txt',
      '    b.txt',
      '  Day 2/',
      '    c.txt',
      '  notes.txt',
      'readme.txt',
    ])
  })

  it('orders names the way a person counts: Item 2 before Item 10', () => {
    expect(names(['Item 10/a.txt', 'Item 2/a.txt'])).toEqual([
      'Item 2/',
      '  a.txt',
      'Item 10/',
      '  a.txt',
    ])
  })

  it('says how many files each folder holds, at any depth', () => {
    const rows = pathsToRows(
      ['A/B/1', 'A/B/2', 'A/3', 'C/4'].map((path) => ({ path })),
    )

    expect(
      rows.filter((r) => r.kind === 'folder').map((r) => [r.name, r.count]),
    ).toEqual([
      ['A', 3],
      ['B', 2],
      ['C', 1],
    ])
  })

  it('keeps a file’s size and whether it can be reached', () => {
    const [file] = pathsToRows([{ path: 'a.txt', size: 12, available: false }])

    expect(file).toMatchObject({ kind: 'file', size: 12, available: false })
  })

  it('is flat when there are no folders, and empty when there are no files', () => {
    expect(names(['b.txt', 'a.txt'])).toEqual(['a.txt', 'b.txt'])
    expect(pathsToRows([])).toEqual([])
    expect(pathsToRows([{ path: '' }])).toEqual([])
  })

  it('treats the same folder name under different parents as different folders', () => {
    expect(names(['A/x/1', 'B/x/2'])).toEqual([
      'A/',
      '  x/',
      '    1',
      'B/',
      '  x/',
      '    2',
    ])
  })
})

describe('collapsing folders', () => {
  const rows = pathsToRows(
    ['A/B/1', 'A/B/2', 'A/3', 'C/4'].map((path) => ({ path })),
  )
  const shown = (collapsed: number[]) =>
    visibleRows(rows, new Set(collapsed)).map((v) => v.row.name)

  it('shows everything when nothing is collapsed', () => {
    expect(shown([])).toEqual(['A', 'B', '1', '2', '3', 'C', '4'])
  })

  it('hides what is under a collapsed folder but not the folder', () => {
    expect(shown([1])).toEqual(['A', 'B', '3', 'C', '4']) // B collapsed
    expect(shown([0])).toEqual(['A', 'C', '4']) // A collapsed: B and its files go too
  })

  it('keeps each row’s own index, so it can be toggled again', () => {
    expect(visibleRows(rows, new Set([0])).map((v) => v.index)).toEqual([
      0, 5, 6,
    ])
  })

  it('collapsing a folder inside a collapsed one changes nothing visible', () => {
    expect(shown([0, 1])).toEqual(['A', 'C', '4'])
  })
})

describe('tables in the tree', () => {
  it('sit among the files in the folder they are written in, told apart by their rows', () => {
    const rows = pathsToRows([
      { path: 'A/s1/s1.txt', size: 5 },
      { path: 'A/Selections.csv', rows: 2 },
      { path: 'Recordings.csv', rows: 7 },
    ])

    expect(rows.map((r) => [r.depth, r.kind, r.name, r.rows])).toEqual([
      [0, 'folder', 'A', undefined],
      [1, 'folder', 's1', undefined],
      [2, 'file', 's1.txt', undefined],
      [1, 'table', 'Selections.csv', 2],
      [0, 'table', 'Recordings.csv', 7],
    ])
  })

  it('count in the folders that hold them', () => {
    const rows = pathsToRows([
      { path: 'A/x.txt' },
      { path: 'A/T.csv', rows: 1 },
    ])

    expect(rows[0]).toMatchObject({ kind: 'folder', name: 'A', count: 2 })
  })
})
