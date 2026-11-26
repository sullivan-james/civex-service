import { describe, expect, it, vi } from 'vitest'
import type { ImportBatch, ImportColumn } from '../../api/imports'
import type { Schema } from '../../api/schemas'
import {
  LEAVE_OUT,
  NEW_FIELD,
  PART_ROWS,
  buildRequest,
  kindKeyFor,
  matchable,
  nameFromFile,
  problemsByRow,
  runInParts,
  suggestMatch,
  suggestSettings,
  summary,
  whyNot,
  type Choices,
} from './importPlan'

const col = (heading: string, key: string, dtype = 'string'): ImportColumn => ({
  heading,
  label: heading,
  key,
  dtype,
  blanks: 0,
})
const COLUMNS = [
  col('ID', 'id'),
  col('First Name', 'first_name'),
  col('Age', 'age', 'integer'),
]
const field = (name: string, type = 'string') => ({
  id: name,
  name,
  label: null,
  type,
  required: false,
  restrictions: {},
  default: null,
  position: null,
})
const SCHEMA: Schema = {
  id: 's',
  name: 'person',
  label: null,
  description: null,
  parent_id: null,
  display_template: null,
  unique_keys: [['id']],
  fields: [field('id'), field('age', 'integer'), field('photo', 'file')],
  deleted_at: null,
}
const SHEET = {
  filename: 'p.csv',
  sheets: [],
  sheet: null,
  columns: COLUMNS,
  rows: [],
  total: 3,
}
const choices = (over: Partial<Choices> = {}): Choices => ({
  filename: 'p.csv',
  sha256: 'abc',
  sheet: SHEET,
  target: { kind: 'new', label: 'People' },
  schema: undefined,
  collection: 'study',
  settings: suggestSettings(COLUMNS, undefined),
  match: '',
  ifExists: 'update',
  kinds: ['study_thing'],
  ...over,
})

describe('where columns go to start with', () => {
  it('makes a field of the suggested type for every column of a new kind', () => {
    expect(suggestSettings(COLUMNS, undefined)).toEqual([
      { heading: 'ID', goesIn: NEW_FIELD, dtype: 'string' },
      { heading: 'First Name', goesIn: NEW_FIELD, dtype: 'string' },
      { heading: 'Age', goesIn: NEW_FIELD, dtype: 'integer' },
    ])
  })

  it('uses the fields a kind already has, and makes the rest', () => {
    const s = suggestSettings(COLUMNS, SCHEMA)
    expect(s.map((x) => x.goesIn)).toEqual(['id', NEW_FIELD, 'age'])
  })

  it('matches by the one-field unique key when its column is brought in', () => {
    expect(suggestMatch(suggestSettings(COLUMNS, SCHEMA), SCHEMA)).toBe('ID')
    expect(suggestMatch(suggestSettings(COLUMNS, undefined), undefined)).toBe(
      '',
    )
  })

  it('offers only columns that can be matched by', () => {
    const settings = suggestSettings(COLUMNS, SCHEMA)
    settings[0] = { ...settings[0], goesIn: LEAVE_OUT }
    expect(matchable(COLUMNS, settings, SCHEMA).map((c) => c.heading)).toEqual([
      'First Name',
      'Age',
    ])
  })
})

describe('names', () => {
  it('derives a kind key different from the kinds there are', () => {
    expect(kindKeyFor('Field Sites', [])).toBe('field_sites')
    expect(kindKeyFor('Field Sites', ['field_sites'])).toBe('field_sites_2')
    expect(kindKeyFor('', [])).toBe('records')
  })
  it('names a new kind from the file', () => {
    expect(nameFromFile('field_sites-2024.xlsx')).toBe('Field sites 2024')
  })
})

describe('the request', () => {
  it('asks for a new kind and its fields', () => {
    const r = buildRequest(choices({ match: 'ID' }))
    expect(r.kind).toBe('people')
    expect(r.kind_label).toBe('People')
    expect(r.columns[1]).toMatchObject({
      heading: 'First Name',
      field: 'first_name',
      create: true,
    })
    expect(r.match_on).toEqual(['id'])
  })

  it('keeps a new field apart from one already there', () => {
    const settings = suggestSettings(COLUMNS, SCHEMA)
    settings[1] = { ...settings[1], goesIn: NEW_FIELD }
    const r = buildRequest(
      choices({
        target: { kind: 'existing', name: 'person' },
        schema: { ...SCHEMA, fields: [...SCHEMA.fields, field('first_name')] },
        settings,
      }),
    )
    expect(r.kind_label).toBeNull()
    expect(r.columns[1].field).toBe('first_name_2')
  })

  it('adds every row when nothing is matched by', () => {
    expect(buildRequest(choices({ ifExists: 'skip' })).if_exists).toBe(
      'add_new',
    )
    expect(
      buildRequest(choices({ match: 'ID', ifExists: 'skip' })).if_exists,
    ).toBe('skip')
  })

  it('says why it cannot be used yet', () => {
    expect(whyNot(choices())).toBeNull()
    expect(whyNot(choices({ target: { kind: 'new', label: ' ' } }))).toMatch(
      /Name the new kind/,
    )
    const none = COLUMNS.map((c) => ({
      heading: c.heading,
      goesIn: LEAVE_OUT,
      dtype: 'string',
    }))
    expect(whyNot(choices({ settings: none }))).toMatch(/at least one column/)
    const twice = suggestSettings(COLUMNS, SCHEMA)
    twice[2] = { ...twice[2], goesIn: 'id' }
    expect(whyNot(choices({ settings: twice, schema: SCHEMA }))).toMatch(
      /same field/,
    )
  })
})

describe('problems', () => {
  it('are found by row', () => {
    const m = problemsByRow([
      "Row 3: age: 'x' is not a whole number",
      'Row 3: another',
      'Row 12: no id to match it by',
      'something else',
    ])
    expect(m.get(3)).toBe("age: 'x' is not a whole number")
    expect(m.get(12)).toBe('no id to match it by')
    expect(m.size).toBe(2)
  })
})

describe('going through the file in parts', () => {
  const part = (start: number, read: number, done = false): ImportBatch => ({
    start,
    read,
    created: read,
    updated: 0,
    unchanged: 0,
    skipped: 0,
    problems: [],
    done,
  })

  it('asks for each part in turn and reports progress', async () => {
    const total = PART_ROWS * 2 + 5
    const run = vi.fn(async (start: number, limit: number) =>
      part(start, Math.min(limit, total - start), start + limit >= total),
    )
    const seen: number[] = []
    const r = await runInParts(run, total, (_t, next) => seen.push(next))
    expect(run.mock.calls.map((c) => c[0])).toEqual([
      0,
      PART_ROWS,
      PART_ROWS * 2,
    ])
    expect(seen).toEqual([PART_ROWS, PART_ROWS * 2, total])
    expect(r.totals.created).toBe(total)
    expect(r.error).toBeNull()
  })

  it('stops at a failure and says where to carry on from', async () => {
    let calls = 0
    const run = async (start: number) => {
      if (++calls === 2) throw new Error('lost')
      return part(start, PART_ROWS)
    }
    const r = await runInParts(run, PART_ROWS * 5, () => {})
    expect(String(r.error)).toMatch(/lost/)
    expect(r.next).toBe(PART_ROWS)
    expect(r.totals.created).toBe(PART_ROWS)
    // carrying on adds to what was done
    const again = await runInParts(
      async (start) => part(start, PART_ROWS, true),
      PART_ROWS * 5,
      () => {},
      { from: r.next, totals: r.totals },
    )
    expect(again.totals.created).toBe(PART_ROWS * 2)
  })

  it('stops when told to', async () => {
    const controller = new AbortController()
    const run = vi.fn(async (start: number) => {
      controller.abort()
      return part(start, PART_ROWS)
    })
    const r = await runInParts(run, PART_ROWS * 4, () => {}, {
      signal: controller.signal,
    })
    expect(r.cancelled).toBe(true)
    expect(run).toHaveBeenCalledTimes(1)
  })

  it('says what was done in words', () => {
    expect(
      summary({
        read: 9,
        created: 1200,
        updated: 3,
        unchanged: 0,
        skipped: 0,
        problems: [],
      }),
    ).toBe('1,200 added, 3 changed.')
  })
})
