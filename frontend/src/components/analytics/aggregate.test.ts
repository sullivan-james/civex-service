import { describe, it, expect } from 'vitest'
import { jobSuccessRateSeries, sumFailuresByPlugin } from './aggregate'

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
