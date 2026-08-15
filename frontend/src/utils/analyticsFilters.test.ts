import { describe, it, expect } from 'vitest'
import {
  defaultAnalyticsFilters,
  parseAnalyticsFilters,
  applyAnalyticsFilterPatch,
  toAnalyticsQueryParams,
} from './analyticsFilters'

const NOW = new Date('2026-08-15T12:00:00.000Z')

describe('defaultAnalyticsFilters', () => {
  it('defaults to the last 30 days with every other filter unset', () => {
    const defaults = defaultAnalyticsFilters(NOW)
    expect(defaults.end).toBe(NOW.toISOString())
    expect(defaults.start).toBe('2026-07-16T12:00:00.000Z')
    expect(defaults.bucket).toBe('day')
    expect(defaults.dataset).toBeNull()
    expect(defaults.schema).toBeNull()
    expect(defaults.workflowId).toBeNull()
    expect(defaults.pluginId).toBeNull()
    expect(defaults.status).toBeNull()
    expect(defaults.trigger).toBeNull()
  })
})

describe('parseAnalyticsFilters', () => {
  it('falls back to defaults when the querystring is empty', () => {
    const filters = parseAnalyticsFilters(new URLSearchParams(), NOW)
    expect(filters).toEqual(defaultAnalyticsFilters(NOW))
  })

  it('reads explicit values over their defaults', () => {
    const params = new URLSearchParams({
      start: '2026-01-01T00:00:00.000Z',
      end: '2026-02-01T00:00:00.000Z',
      bucket: 'week',
      dataset: 'invoices',
      schema: 'invoice',
      workflow_id: 'extract-invoice',
      plugin_id: 'civex.load_file',
      status: 'failed',
      trigger: 'record_created',
    })
    const filters = parseAnalyticsFilters(params, NOW)
    expect(filters).toEqual({
      start: '2026-01-01T00:00:00.000Z',
      end: '2026-02-01T00:00:00.000Z',
      bucket: 'week',
      dataset: 'invoices',
      schema: 'invoice',
      workflowId: 'extract-invoice',
      pluginId: 'civex.load_file',
      status: 'failed',
      trigger: 'record_created',
    })
  })

  it('ignores an invalid bucket or date and falls back to the default', () => {
    const params = new URLSearchParams({
      start: 'not-a-date',
      bucket: 'fortnight',
    })
    const filters = parseAnalyticsFilters(params, NOW)
    expect(filters.start).toBe(defaultAnalyticsFilters(NOW).start)
    expect(filters.bucket).toBe('day')
  })
})

describe('applyAnalyticsFilterPatch', () => {
  it('sets changed keys and leaves the rest untouched', () => {
    const params = new URLSearchParams({ dataset: 'invoices' })
    const next = applyAnalyticsFilterPatch(params, { schema: 'invoice' })
    expect(next.get('dataset')).toBe('invoices')
    expect(next.get('schema')).toBe('invoice')
  })

  it('clears a param back to its implicit default on null or empty string', () => {
    const params = new URLSearchParams({
      dataset: 'invoices',
      status: 'failed',
    })
    const next = applyAnalyticsFilterPatch(params, {
      dataset: null,
      status: '',
    })
    expect(next.has('dataset')).toBe(false)
    expect(next.has('status')).toBe(false)
  })

  it('maps camelCase keys to the API contract param names', () => {
    const next = applyAnalyticsFilterPatch(new URLSearchParams(), {
      workflowId: 'wf-1',
      pluginId: 'civex.load_file',
    })
    expect(next.get('workflow_id')).toBe('wf-1')
    expect(next.get('plugin_id')).toBe('civex.load_file')
  })
})

describe('toAnalyticsQueryParams', () => {
  it('always includes start/end/bucket and omits unset filters', () => {
    const params = toAnalyticsQueryParams(defaultAnalyticsFilters(NOW))
    expect(params.get('start')).toBe(defaultAnalyticsFilters(NOW).start)
    expect(params.get('end')).toBe(NOW.toISOString())
    expect(params.get('bucket')).toBe('day')
    expect(params.has('dataset')).toBe(false)
    expect(params.has('workflow_id')).toBe(false)
  })

  it('includes optional filters when set', () => {
    const filters = {
      ...defaultAnalyticsFilters(NOW),
      dataset: 'invoices',
      workflowId: 'extract-invoice',
    }
    const params = toAnalyticsQueryParams(filters)
    expect(params.get('dataset')).toBe('invoices')
    expect(params.get('workflow_id')).toBe('extract-invoice')
  })
})
