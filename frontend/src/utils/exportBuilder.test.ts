import { describe, it, expect } from 'vitest'
import type { ExportDefinition } from '../api/exportDefinitions'
import type { Schema } from '../api/schemas'
import {
  definitionBody,
  describeDefinition,
  draftFrom,
  emptyDraft,
  kindsIn,
  previewSelection,
  describeTable,
} from './exportBuilder'
import { layoutNodes } from './exportLayouts'

const field = (name: string, type: string) => ({
  id: name,
  name,
  label: null,
  type,
  required: false,
  restrictions: {},
  default: null,
  position: null,
})
const schema = (
  name: string,
  parent: string | null,
  fields: [string, string][],
  deleted = false,
): Schema => ({
  id: name,
  name,
  label: null,
  description: null,
  parent_id: parent,
  display_template: null,
  fields: fields.map(([n, t]) => field(n, t)),
  deleted_at: deleted ? '2026-01-01' : null,
})

// Encounter -> Recording -> Selection: audio on the Recordings, contours and
// tables on the Selections. An unrelated Site with a scan.
const encounter = schema('encounter', null, [['site', 'string']])
const recording = schema('recording', 'encounter', [['audio', 'file']])
const selection = schema('selection', 'recording', [
  ['contour', 'file'],
  ['extras', 'file_list'],
  ['label', 'string'],
])
const site = schema('site', null, [['scan', 'file']])
const all = [encounter, recording, selection, site]

describe('the kinds an export for a schema can draw from', () => {
  it('are the schema and everything beneath it, and nothing else', () => {
    expect(kindsIn(all, 'encounter').map((s) => s.name)).toEqual([
      'encounter',
      'recording',
      'selection',
    ])
    expect(kindsIn(all, 'selection').map((s) => s.name)).toEqual(['selection'])
    expect(kindsIn(all, 'nope')).toEqual([])
  })

  it('leave out deleted kinds', () => {
    const gone = schema('gone', 'encounter', [['f', 'file']], true)

    expect(
      kindsIn([...all, gone], 'encounter').map((s) => s.name),
    ).not.toContain('gone')
  })
})

describe('what is saved', () => {
  it('is the draft, with nothing about a collection or a record', () => {
    expect(
      definitionBody({
        ...emptyDraft,
        name: '  Contours  ',
        holder: 'selection',
        fields: ['contour'],
        layout: 'flat',
      }),
    ).toEqual({
      name: 'Contours',
      holder: 'selection',
      fields: ['contour'],
      filter_tree: null,
      files_layout: 'flat',
      include_files: true,
      tables: [],
    })
  })

  it('leaves a filter out when there is no kind of record for it to test', () => {
    const filter = { field: 'label', op: 'eq', value: 'x' } as never

    expect(
      definitionBody({ ...emptyDraft, name: 'a', filter }).filter_tree,
    ).toBeNull()
    expect(
      definitionBody({ ...emptyDraft, name: 'a', holder: 'selection', filter })
        .filter_tree,
    ).toEqual(filter)
  })

  it('round-trips an existing export, to change it', () => {
    const def: ExportDefinition = {
      id: '1',
      schema_id: 's',
      schema_name: 'encounter',
      name: 'Contours',
      holder: null,
      fields: ['audio'],
      filter_tree: null,
      files_layout: 'grouped',
      include_files: true,
      tables: [],
    }

    expect(draftFrom(def)).toEqual({
      name: 'Contours',
      holder: '',
      fields: ['audio'],
      filter: null,
      layout: 'grouped',
      files: true,
      tables: [],
    })
  })
})

describe('previewing a draft against the data', () => {
  it('takes one kind, wherever it is, when a kind is chosen', () => {
    expect(
      previewSelection(
        {
          ...emptyDraft,
          holder: 'selection',
          fields: ['contour'],
          layout: 'flat',
        },
        'encounter',
        all,
      ),
    ).toEqual({
      schema_name: 'selection',
      kinds: undefined,
      filter: undefined,
      fields: ['contour'],
      layout: 'flat',
      tables: [],
    })
  })

  it('stays within the schema’s own tree when any kind beneath it is wanted', () => {
    const sel = previewSelection(emptyDraft, 'encounter', all)

    expect(sel.schema_name).toBeUndefined()
    expect(sel.kinds).toEqual(['encounter', 'recording', 'selection'])
    expect(sel.kinds).not.toContain('site')
  })
})

describe('saying what an export is', () => {
  it('names the files, the kind, any filter and the layout', () => {
    expect(
      describeDefinition(
        {
          holder: 'selection',
          fields: ['contour'],
          filter_tree: null,
          files_layout: 'flat',
        },
        all,
      ),
    ).toBe('contour of Selection · all in one folder')
    expect(
      describeDefinition({
        holder: null,
        fields: [],
        filter_tree: { field: 'a', op: 'eq', value: 1 } as never,
        files_layout: 'tree',
      }),
    ).toBe('every file of any kind beneath · filtered · a folder per record')
  })
})

describe('layouts as folders', () => {
  const names = (layout: 'tree' | 'grouped' | 'flat') =>
    layoutNodes(layout).map((n) => `${'  '.repeat(n.depth)}${n.name}`)

  it('draw a folder for every level in a tree', () => {
    expect(names('tree')).toEqual([
      'Parent 1',
      '  Child 1',
      '    Item 1',
      '      file.txt',
      '    Item 2',
      '      file.txt',
    ])
  })

  it('gather the last level into one folder when grouped, naming files for their item', () => {
    expect(names('grouped')).toEqual([
      'Parent 1',
      '  Child 1',
      '    Items',
      '      Item 1 - file.txt',
      '      Item 2 - file.txt',
    ])
  })

  it('are only files when flat', () => {
    const nodes = layoutNodes('flat')

    expect(nodes.every((n) => n.kind === 'file' && n.depth === 0)).toBe(true)
    expect(nodes.map((n) => n.name)).toEqual([
      'Item 1 - file.txt',
      'Item 2 - file.txt',
      'Item 3 - file.txt',
    ])
  })

  it('use neutral names that fit any data', () => {
    const everything = (['tree', 'grouped', 'flat'] as const).flatMap((l) =>
      layoutNodes(l).map((n) => n.name),
    )

    expect(everything.join(' ')).not.toMatch(/encounter|recording|selection/i)
  })
})

describe('tables in an export', () => {
  const table = { format: 'xlsx' as const, columns: ['label'] }

  it('are saved with the export, and tables alone save no file fields', () => {
    const body = definitionBody({
      ...emptyDraft,
      name: 'Tables',
      holder: 'selection',
      fields: ['contour'],
      files: false,
      tables: [table],
    })

    expect(body).toMatchObject({
      include_files: false,
      fields: [],
      tables: [table],
    })
  })

  it('go into a one-off selection, which then takes no files if asked not to', () => {
    const sel = previewSelection(
      { ...emptyDraft, holder: 'selection', files: false, tables: [table] },
      'encounter',
      all,
    )

    expect(sel).toMatchObject({ files: false, tables: [table] })
  })

  it('are described beside, or instead of, the files', () => {
    const def = {
      holder: 'selection',
      fields: [],
      files_layout: 'flat' as const,
      filter_tree: null,
    }

    expect(describeDefinition({ ...def, tables: [table] })).toContain('Excel')
    expect(
      describeDefinition({ ...def, include_files: false, tables: [table] }),
    ).toMatch(/^Tables of/)
    expect(
      describeDefinition({ ...def, tables: [table, { format: 'csv' }] }),
    ).toContain('2 tables')
  })

  it('come back as they were saved', () => {
    const spec = {
      format: 'csv' as const,
      kind: 'selection',
      where: 'recording',
      columns: null,
    }
    const def: ExportDefinition = {
      id: 'd',
      schema_id: 'encounter',
      schema_name: 'encounter',
      name: 'Sheets',
      holder: 'selection',
      fields: [],
      filter_tree: null,
      files_layout: 'tree',
      include_files: true,
      tables: [spec],
    }

    expect(draftFrom(def).tables).toEqual([spec])
    expect(definitionBody(draftFrom(def)).tables).toEqual([spec])
  })
})

describe('a table in words', () => {
  it('says what it lists and where it goes', () => {
    expect(
      describeTable(
        { format: 'csv', kind: 'selection', where: 'recording' },
        all,
      ),
    ).toBe('CSV of Selection in each Recording folder')
    expect(describeTable({ format: 'xlsx', columns: ['a', 'b'] }, all)).toBe(
      'Excel of each kind taken at the top · 2 columns',
    )
    expect(
      describeTable(
        {
          format: 'csv',
          kind: 'selection',
          where: 'selection',
          shape: 'fields',
        },
        all,
      ),
    ).toBe('CSV of Selection in each record’s folder, as its details')
  })
})
