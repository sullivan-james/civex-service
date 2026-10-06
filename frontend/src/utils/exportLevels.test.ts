import { describe, expect, it } from 'vitest'
import { emptyDraft, type Draft } from './exportBuilder'
import {
  filesOn,
  filterKind,
  findTable,
  hasTable,
  trailTo,
  updateTable,
  levelsFor,
  otherTables,
  pluralize,
  selectedFiles,
  tableAll,
  tableDetails,
  tableList,
  withFileFields,
  withTable,
  writtenInFolders,
} from './exportLevels'
import {
  ENCOUNTER,
  RECORDING,
  SCHEMAS,
  SELECTION,
} from '../components/exports/exportsTestSupport'

const levels = levelsFor(SCHEMAS, 'encounter')
const draft = (over: Partial<Draft> = {}): Draft => ({ ...emptyDraft, ...over })

describe('the levels of an export', () => {
  it('are the schema and what is beneath it, each with what is inside it', () => {
    expect(levels.map((l) => [l.schema.name, l.depth])).toEqual([
      ['encounter', 0],
      ['recording', 1],
      ['selection', 2],
    ])
    expect(levels[0].children.map((c) => c.name)).toEqual(['recording'])
    expect(levels[2].children).toEqual([])
  })

  it('list the files a kind defines itself, not the ones it inherits', () => {
    expect(levels.map((l) => l.fileFields)).toEqual([
      [],
      ['audio'],
      ['contour', 'table'],
    ])
  })

  it('start from a kind when a list is of one, and cover every tree with none', () => {
    expect(levelsFor(SCHEMAS, 'recording').map((l) => l.schema.name)).toEqual([
      'recording',
      'selection',
    ])
    expect(levelsFor(SCHEMAS).map((l) => l.schema.name)).toEqual([
      'encounter',
      'recording',
      'selection',
    ])
  })

  it('leave out a deleted kind', () => {
    const gone = { ...SELECTION, deleted_at: '2026-01-01' }
    expect(
      levelsFor([ENCOUNTER, RECORDING, gone], 'encounter').map(
        (l) => l.schema.name,
      ),
    ).toEqual(['encounter', 'recording'])
  })
})

describe('the tables a tick stands for', () => {
  it('are added in the shape the server takes, and taken out again', () => {
    const tables = withTable(
      withTable([], tableDetails('selection'), true, 'xlsx'),
      tableList('recording', 'selection'),
      true,
      'xlsx',
    )

    expect(tables).toEqual([
      {
        format: 'xlsx',
        columns: null,
        kind: 'selection',
        where: 'selection',
        shape: 'fields',
      },
      { format: 'xlsx', columns: null, kind: 'selection', where: 'recording' },
    ])
    expect(hasTable(tables, tableDetails('selection'))).toBe(true)
    expect(hasTable(tables, tableAll('selection'))).toBe(false)
    expect(
      withTable(tables, tableDetails('selection'), false, 'xlsx'),
    ).toHaveLength(1)
  })

  it('are not added twice', () => {
    const once = withTable([], tableAll('selection'), true, 'csv')
    expect(withTable(once, tableAll('selection'), true, 'csv')).toBe(once)
  })

  it('find the one a tick stands for, and change just that one', () => {
    const tables = [
      { format: 'csv' as const, kind: 'selection', columns: ['sname'] },
      { format: 'csv' as const, kind: 'recording' },
    ]

    expect(findTable(tables, tableAll('recording'))).toBe(tables[1])
    expect(findTable(tables, tableAll('encounter'))).toBeUndefined()
    expect(
      updateTable(tables, tableAll('selection'), {
        format: 'xlsx',
        name: 'Sel',
      }),
    ).toEqual([
      { format: 'xlsx', kind: 'selection', columns: ['sname'], name: 'Sel' },
      { format: 'csv', kind: 'recording' },
    ])
  })

  it('that no tick stands for are the ones left for More options', () => {
    const tables = [
      {
        format: 'csv' as const,
        kind: 'selection',
        where: 'selection',
        shape: 'fields' as const,
      },
      { format: 'csv' as const }, // one table of each kind taken
      { format: 'csv' as const, kind: 'nonsense' },
    ]

    expect(otherTables(tables, levels)).toEqual([tables[1], tables[2]])
  })

  it('written in folders need the folder-per-record layout', () => {
    expect(writtenInFolders([{ format: 'csv', kind: 'selection' }])).toBe(false)
    expect(
      writtenInFolders([
        { format: 'csv', kind: 'selection', where: 'recording' },
      ]),
    ).toBe(true)
  })
})

describe('where a level is', () => {
  it('is the kinds from the top down to it', () => {
    expect(trailTo(levels[2], levels).map((s) => s.name)).toEqual([
      'encounter',
      'recording',
      'selection',
    ])
    expect(trailTo(levels[0], levels).map((s) => s.name)).toEqual(['encounter'])
  })

  it('starts at the top of the export, not above it', () => {
    const below = levelsFor(SCHEMAS, 'recording')
    expect(trailTo(below[1], below).map((s) => s.name)).toEqual([
      'recording',
      'selection',
    ])
  })
})

describe('the files at each level', () => {
  it('are all on for an export of any kind with every file', () => {
    expect(selectedFiles(draft(), levels)).toEqual({
      encounter: [],
      recording: ['audio'],
      selection: ['contour', 'table'],
    })
  })

  it('are only the chosen fields of the kind that holds them', () => {
    const d = draft({ holder: 'selection', fields: ['contour'] })

    expect(selectedFiles(d, levels)).toEqual({
      encounter: [],
      recording: [],
      selection: ['contour'],
    })
    expect(filesOn(d, levels)).toBe(true)
  })

  it('are off when the files are', () => {
    expect(filesOn(draft({ files: false }), levels)).toBe(false)
  })
})

describe('changing the files', () => {
  it('to one level makes that the kind that holds them', () => {
    expect(withFileFields(draft(), levels, 'recording', [])).toMatchObject({
      files: true,
      holder: 'selection',
      fields: ['contour', 'table'],
    })
    const patch = withFileFields(
      draft({ holder: 'selection', fields: ['contour'] }),
      levels,
      'selection',
      ['contour', 'table'],
    )
    expect(patch).toMatchObject({ holder: 'selection' })
  })

  it('across levels means any kind beneath, naming the fields unless it is every one', () => {
    const some = withFileFields(
      draft({ holder: 'selection', fields: ['contour'] }),
      levels,
      'recording',
      ['audio'],
    )
    expect(some).toMatchObject({
      files: true,
      holder: '',
      fields: ['audio', 'contour'],
    })

    const all = withFileFields(
      draft({ holder: 'selection', fields: ['contour', 'table'] }),
      levels,
      'recording',
      ['audio'],
    )
    expect(all).toMatchObject({ holder: '', fields: [] })
  })

  it('to none at all turns the files off', () => {
    expect(
      withFileFields(
        draft({ holder: 'selection', fields: ['contour'] }),
        levels,
        'selection',
        [],
      ),
    ).toMatchObject({ files: false, holder: '', fields: [] })
  })

  it('clears a filter when the kind it tested is no longer the one', () => {
    const d = draft({
      holder: 'selection',
      fields: ['contour'],
      filter: { and: [] } as never,
    })

    expect(withFileFields(d, levels, 'recording', ['audio'])).toMatchObject({
      filter: null,
    })
    expect(
      withFileFields(d, levels, 'selection', ['contour', 'table']),
    ).not.toHaveProperty('filter')
  })

  it('know the one kind an only-where filter tests, when there is one', () => {
    expect(
      filterKind(draft({ holder: 'selection', fields: ['contour'] }), levels),
    ).toBe('selection')
    expect(filterKind(draft(), levels)).toBeNull()
  })
})

describe('plurals in a heading', () => {
  it('follow the plain rules', () => {
    expect(pluralize('Selection')).toBe('Selections')
    expect(pluralize('Study')).toBe('Studies')
    expect(pluralize('Key')).toBe('Keys')
    expect(pluralize('Class')).toBe('Classes')
    expect(pluralize('Box')).toBe('Boxes')
  })
})
