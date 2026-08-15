import type { TimeSeriesPoint, TimeSeriesSeries } from './TimeSeriesChart'
import type { BarBreakdownDatum } from './BarBreakdown'
import type {
  DurationHistogramBin,
  DurationHistogramPercentile,
} from './DurationHistogram'

// Fixture data for the analytics primitives, so widgets (and this
// directory's own tests) can render charts without depending on any live
// endpoint. Shapes mirror what a real /analytics response is expected to
// look like, but the values are hand-picked, not sampled.

export const timeSeriesFixtureData: TimeSeriesPoint[] = [
  { date: '08-01', succeeded: 42, failed: 3 },
  { date: '08-02', succeeded: 51, failed: 2 },
  { date: '08-03', succeeded: 38, failed: 6 },
  { date: '08-04', succeeded: 60, failed: 1 },
  { date: '08-05', succeeded: 55, failed: 4 },
  { date: '08-06', succeeded: 47, failed: 2 },
  { date: '08-07', succeeded: 63, failed: 0 },
]

export const timeSeriesFixtureSeries: TimeSeriesSeries[] = [
  { key: 'succeeded', label: 'Succeeded' },
  { key: 'failed', label: 'Failed' },
]

export const barBreakdownFixtureData: BarBreakdownDatum[] = [
  { label: 'invoice', value: 128 },
  { label: 'customer', value: 94 },
  { label: 'shipment', value: 61 },
  { label: 'contract', value: 23 },
  { label: 'vendor', value: 9 },
]

export const durationHistogramFixtureBins: DurationHistogramBin[] = [
  { label: '0-1s', count: 12 },
  { label: '1-2s', count: 34 },
  { label: '2-5s', count: 58 },
  { label: '5-10s', count: 21 },
  { label: '10-30s', count: 9 },
  { label: '30s+', count: 3 },
]

export const durationHistogramFixturePercentiles: DurationHistogramPercentile[] =
  [
    { label: 'p50', binLabel: '2-5s' },
    { label: 'p95', binLabel: '10-30s' },
  ]
