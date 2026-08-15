import { describe, it, expect } from 'vitest'
import {
  jobSuccessRateSeries,
  sumFailuresByPlugin,
  recordGrowthSeries,
  sumRecordCountsBySchema,
} from './aggregate'

describe('jobSuccessRateSeries', () => {
  it('computes the completed share of settled runs per bucket', () => {
    const { series, totalCompleted, totalFailed } = jobSuccessRateSeries([
      { bucket: '2026-08-01', status: 'completed', count: 3 },
      { bucket: '2026-08-01', status: 'failed', count: 1 },
      { bucket: '2026-08-02', status: 'completed', count: 1 },
      { bucket: '2026-08-02', status: 'failed', count: 1 },
    ])
    expect(series).toEqual([
      { date: '2026-08-01', rate: 75 },
      { date: '2026-08-02', rate: 50 },
    ])
    expect(totalCompleted).toBe(4)
    expect(totalFailed).toBe(2)
  })

  it('ignores pending/running runs -- unsettled, not failures', () => {
    const { series, totalCompleted, totalFailed } = jobSuccessRateSeries([
      { bucket: '2026-08-01', status: 'completed', count: 2 },
      { bucket: '2026-08-01', status: 'pending', count: 5 },
      { bucket: '2026-08-01', status: 'running', count: 5 },
    ])
    expect(series).toEqual([{ date: '2026-08-01', rate: 100 }])
    expect(totalCompleted).toBe(2)
    expect(totalFailed).toBe(0)
  })

  it('returns an empty series for no data', () => {
    expect(jobSuccessRateSeries([])).toEqual({
      series: [],
      totalCompleted: 0,
      totalFailed: 0,
    })
  })

  it('sorts buckets chronologically regardless of input order', () => {
    const { series } = jobSuccessRateSeries([
      { bucket: '2026-08-03', status: 'completed', count: 1 },
      { bucket: '2026-08-01', status: 'completed', count: 1 },
      { bucket: '2026-08-02', status: 'completed', count: 1 },
    ])
    expect(series.map((s) => s.date)).toEqual([
      '2026-08-01',
      '2026-08-02',
      '2026-08-03',
    ])
  })
})

describe('sumFailuresByPlugin', () => {
  it('sums counts across buckets, most failures first', () => {
    const bars = sumFailuresByPlugin([
      { bucket: '2026-08-01', plugin: 'civex.load_file', count: 2 },
      { bucket: '2026-08-02', plugin: 'civex.load_file', count: 3 },
      { bucket: '2026-08-01', plugin: 'civex.get_field', count: 1 },
    ])
    expect(bars).toEqual([
      { label: 'civex.load_file', value: 5 },
      { label: 'civex.get_field', value: 1 },
    ])
  })

  it('returns an empty list for no data', () => {
    expect(sumFailuresByPlugin([])).toEqual([])
  })
})

describe('recordGrowthSeries', () => {
  it('pivots into one point per bucket with one key per dataset/schema combo', () => {
    const { series, seriesKeys, total } = recordGrowthSeries([
      { bucket: '2026-08-01', dataset: 'study', schema_name: 'doc', count: 2 },
      { bucket: '2026-08-01', dataset: 'study', schema_name: 'note', count: 1 },
      { bucket: '2026-08-02', dataset: 'study', schema_name: 'doc', count: 3 },
    ])
    expect(series).toEqual([
      { date: '2026-08-01', 'study/doc': 2, 'study/note': 1 },
      { date: '2026-08-02', 'study/doc': 3 },
    ])
    expect(seriesKeys).toEqual([
      { key: 'study/doc', label: 'study/doc' },
      { key: 'study/note', label: 'study/note' },
    ])
    expect(total).toBe(6)
  })

  it('returns an empty summary for no data', () => {
    expect(recordGrowthSeries([])).toEqual({
      series: [],
      seriesKeys: [],
      total: 0,
    })
  })
})

describe('sumRecordCountsBySchema', () => {
  it('sums counts across datasets, most records first', () => {
    const bars = sumRecordCountsBySchema([
      { dataset: 'study', schema_name: 'doc', count: 2 },
      { dataset: 'other', schema_name: 'doc', count: 3 },
      { dataset: 'study', schema_name: 'note', count: 1 },
    ])
    expect(bars).toEqual([
      { label: 'doc', value: 5 },
      { label: 'note', value: 1 },
    ])
  })

  it('returns an empty list for no data', () => {
    expect(sumRecordCountsBySchema([])).toEqual([])
  })
})
