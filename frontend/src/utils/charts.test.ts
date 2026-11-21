import { describe, expect, it } from 'vitest'
import type { FieldTypeDescriptor } from '../api/schemas'
import type { FilterableField } from './hierarchy'
import {
  buildChart,
  chartTitle,
  chartsFromParam,
  chartsToParam,
  sameCharts,
  recommendedCharts,
  type Usable,
} from './charts'
import { totalsCells, totalsMeasures } from './totals'

const type = (
  name: string,
  grouping: FieldTypeDescriptor['grouping'],
  measures: string[],
): FieldTypeDescriptor =>
  ({ type: name, grouping, measures, buckets: ['year', 'month'] }) as never
const TYPES = {
  string: type('string', 'value', ['filled', 'distinct', 'min', 'max']),
  float: type('float', 'bin', [
    'filled',
    'distinct',
    'min',
    'max',
    'mean',
    'sum',
  ]),
  date: type('date', 'bucket', ['filled', 'distinct', 'min', 'max']),
  geo: type('geo', null, ['filled']),
}
const usable = (
  name: string,
  kind: keyof typeof TYPES,
  restrictions: Record<string, unknown> = {},
): Usable => ({
  field: {
    id: name,
    name,
    label: null,
    type: kind,
    required: false,
    restrictions,
    default: null,
    position: 0,
    sourceSchemaName: 'sample',
    relation: 'self',
  } as FilterableField,
  type: TYPES[kind],
})
const FIELDS = [
  usable('name', 'string'),
  usable('site', 'string'),
  usable('depth', 'float', { unit: 'm' }),
  usable('taken', 'date'),
  usable('spot', 'geo'),
]

describe('a chart’s title, in plain words', () => {
  it('says what each bar shows and what the bars are of', () => {
    const title = (by: string[], m: string) =>
      chartTitle({ id: 'x', group_by: by, measures: [m] }, FIELDS, 'Sample')
    expect(title(['site'], 'count')).toBe('How many samples per site')
    expect(title(['site'], 'mean:depth')).toBe('Average depth per site')
    expect(title(['taken:month'], 'count')).toBe(
      'How many samples per month (taken)',
    )
    expect(title(['depth:5'], 'count')).toBe(
      'How many samples per depth in steps of 5 m',
    )
    expect(title([], 'filled:site')).toBe('How many have site')
    expect(
      chartTitle(
        { id: 'm', map: 'spot', group_by: [], measures: [] },
        FIELDS,
        'Sample',
      ),
    ).toBe('Where they are')
    expect(
      chartTitle(
        { id: 't', title: 'Mine', group_by: [], measures: [] },
        FIELDS,
        'Sample',
      ),
    ).toBe('Mine')
  })

  it('counts a kind beneath by its name', () => {
    const schemas = [{ name: 'reading', label: null }] as never
    expect(
      chartTitle(
        { id: 'x', group_by: ['site'], measures: ['inside:reading'] },
        FIELDS,
        'Sample',
        schemas,
      ),
    ).toBe('How many readings inside per site')
  })
})

describe('the two choices of a new chart', () => {
  it('writes them as a summary does', () => {
    expect(
      buildChart({ by: 'taken', how: 'month', show: 'count', of: '' }),
    ).toMatchObject({ group_by: ['taken:month'], measures: ['count'] })
    expect(
      buildChart({ by: 'site', how: '', show: 'mean', of: 'depth' }),
    ).toMatchObject({ group_by: ['site'], measures: ['mean:depth'] })
  })
})

describe('a list’s own charts in the address', () => {
  it('round trip, and compare without their ids', () => {
    const charts = [
      { id: 'a', group_by: ['site'], measures: ['count'] },
      { id: 'b', map: 'spot', group_by: [], measures: [] },
    ]
    const back = chartsFromParam(chartsToParam(charts))!
    expect(sameCharts(back, charts)).toBe(true)
    expect(sameCharts(back, [{ ...charts[0], id: 'z' }, charts[1]])).toBe(true)
    expect(sameCharts(back, [charts[1], charts[0]])).toBe(false)
    expect(chartsFromParam(null)).toBeNull()
    expect(chartsFromParam('not json')).toBeNull()
  })
})

describe('charts recommended while building one', () => {
  it('come from the kind’s own definition: choices, yes/no, then a date by month', () => {
    const fields = [
      usable('name', 'string'),
      usable('site', 'string', { choices: ['a', 'b'] }),
      usable('depth', 'float'),
      usable('taken', 'date'),
    ]
    expect(recommendedCharts(fields).map((c) => c.group_by[0])).toEqual([
      'site',
      'taken:month',
    ])
    expect(recommendedCharts([usable('name', 'string')])).toEqual([])
  })
})

describe('totals under the table', () => {
  it('asks for number and choice columns and words each cell', () => {
    const fields = [
      FIELDS[2].field,
      { ...FIELDS[1].field, restrictions: { choices: ['a', 'b'] } },
      FIELDS[0].field,
    ]
    expect(totalsMeasures(['name', 'depth', 'site'], fields)).toEqual([
      'mean:depth',
      'min:depth',
      'max:depth',
      'distinct:site',
    ])
    const summary = {
      measure_columns: [
        'mean:depth',
        'min:depth',
        'max:depth',
        'distinct:site',
      ].map((key) => ({ key })),
      total: [12.5, 2, 40, 2],
    } as never
    expect(totalsCells(['name', 'depth', 'site'], summary)).toEqual({
      depth: 'avg 12.5 · 2 to 40',
      site: '2 different',
    })
  })
})
