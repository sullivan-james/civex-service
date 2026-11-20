import { describe, expect, it } from 'vitest'
import type {
  RecordSummary,
  SummaryGroupColumn,
  SummaryMeasureColumn,
  SummaryRow,
} from '../api/records'
import { MAX_SERIES, buildSummaryChart, noChartReason } from './summaryChart'

const col = (over: Partial<SummaryGroupColumn>): SummaryGroupColumn => ({
  key: 'f',
  field: 'f',
  schema_name: 'sample',
  label: 'F',
  type: 'string',
  bucket: null,
  bin: null,
  unit: null,
  ...over,
})
const COUNT: SummaryMeasureColumn = {
  key: 'count',
  measure: 'count',
  label: 'Records',
  field: null,
  schema_name: null,
  type: null,
  unit: null,
}
const MEAN: SummaryMeasureColumn = {
  key: 'mean:depth',
  measure: 'mean',
  label: 'Average depth',
  field: 'depth',
  schema_name: 'sample',
  type: 'float',
  unit: 'm',
}
const g = (value: unknown, extra: Partial<SummaryRow['groups'][0]> = {}) => ({
  value,
  label: value === null ? 'No value' : String(value),
  lower: null,
  upper: null,
  precision: null,
  ...extra,
})
const summary = (
  group_columns: SummaryGroupColumn[],
  rows: SummaryRow[],
  measure_columns = [COUNT],
): RecordSummary => ({
  schema_name: 'sample',
  group_columns,
  measure_columns,
  rows,
  total: [],
  truncated: false,
  limit: 1000,
  timezone: null,
})
const w = (v: unknown) => ({ field: 'f', op: 'eq', value: v })

describe('a summary as a chart', () => {
  it('says why there is none', () => {
    expect(noChartReason(summary([], []))).toMatch(/Add a grouping/)
    expect(noChartReason(summary([col({}), col({}), col({})], []))).toMatch(
      /one or two groupings/,
    )
  })

  it('a histogram fills the empty ranges between with 0', () => {
    const c = col({ type: 'float', bin: 0.1, key: 'depth:0.1' })
    const chart = buildSummaryChart(
      summary(
        [c],
        [
          {
            groups: [g(0.1, { lower: 0.1, upper: 0.2 })],
            values: [2],
            where: w(1),
          },
          {
            groups: [g(0.4, { lower: 0.4, upper: 0.5 })],
            values: [1],
            where: w(4),
          },
        ],
      ),
      null,
    )!
    expect(chart.form).toBe('histogram')
    expect(chart.points.map((p) => [p.axis, p.s0])).toEqual([
      ['0.1', 2],
      ['0.2', 0],
      ['0.3', 0],
      ['0.4', 1],
    ])
    // An empty range lists nothing; a real one its records.
    expect(chart.wheres[1][0]).toBeNull()
    expect(chart.wheres[3][0]).toEqual(w(4))
  })

  it('a time series fills periods; a less precise date and no value sit beside it', () => {
    const c = col({ type: 'date', bucket: 'month', key: 'taken:month' })
    const month = (key: string, lower: string) => g(key, { lower, upper: null })
    const chart = buildSummaryChart(
      summary(
        [c],
        [
          {
            groups: [month('2019', '2019-01-01')].map((x) => ({
              ...x,
              label: '2019, month not known',
              precision: 'year',
            })),
            values: [5, 9],
            where: w('2019'),
          },
          {
            groups: [month('2019-11', '2019-11-01')],
            values: [1, 1.5],
            where: w('nov'),
          },
          {
            groups: [month('2020-02', '2020-02-01')],
            values: [1, 2],
            where: w('feb'),
          },
          { groups: [g(null)], values: [3, 4], where: w(null) },
        ],
        [COUNT, MEAN],
      ),
      'mean:depth',
    )!
    expect(chart.form).toBe('time')
    expect(chart.measure.key).toBe('mean:depth')
    // An average of no records is unknown, not 0: a gap in the line.
    expect(chart.points.map((p) => [p.axis, p.s0])).toEqual([
      ['2019-11', 1.5],
      ['2019-12', null],
      ['2020-01', null],
      ['2020-02', 2],
    ])
    expect(chart.partial.map((a) => a.label)).toEqual(['2019, month not known'])
    expect(chart.noValue.map((a) => [a.label, a.value])).toEqual([
      ['No value', 4],
    ])
  })

  it('a second grouping is the series: the largest few, stacked for counts', () => {
    const a = col({ key: 'habitat' })
    const b = col({ key: 'site', label: 'Site' })
    const rows: SummaryRow[] = []
    for (let i = 0; i < MAX_SERIES + 2; i++)
      rows.push({
        groups: [g('reef'), g(`s${i}`)],
        values: [i + 1],
        where: w(i),
      })
    rows.push({ groups: [g('sand'), g('s6')], values: [10], where: w('x') })
    const chart = buildSummaryChart(summary([a, b], rows), null)!
    expect(chart.stacked).toBe(true)
    expect(chart.series).toHaveLength(MAX_SERIES)
    expect(chart.hiddenSeries).toBe(2)
    expect(chart.series[0].label).toBe('s6') // 7 + 10, the largest
    expect(chart.points.map((p) => p.axis)).toEqual(['reef', 'sand'])
    expect(chart.points[1].s0).toBe(10)
    expect(chart.wheres[1][0]).toEqual(w('x'))
  })
})
