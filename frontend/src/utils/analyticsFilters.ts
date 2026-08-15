/** Shared filter state for the analytics dashboard, synced to the URL
 * querystring so a filtered view is bookmarkable/shareable. Field names and
 * defaults mirror the `AnalyticsFilters` query-param contract every
 * `/analytics/*` endpoint accepts (see `analytics_filters()` in
 * `server/routers/analytics.py`). */

export type AnalyticsBucket = 'day' | 'week' | 'month'

export interface AnalyticsFiltersState {
  /** Inclusive lower bound, UTC ISO string. */
  start: string
  /** Exclusive upper bound, UTC ISO string. */
  end: string
  bucket: AnalyticsBucket
  dataset: string | null
  schema: string | null
  workflowId: string | null
  pluginId: string | null
  status: string | null
  trigger: string | null
}

const BUCKETS: readonly AnalyticsBucket[] = ['day', 'week', 'month']
const DEFAULT_BUCKET: AnalyticsBucket = 'day'
const DEFAULT_RANGE_DAYS = 30
const DAY_MS = 24 * 60 * 60 * 1000

/** Maps each state field to its querystring param name -- the same names
 * `analytics_filters()` reads server-side. */
const PARAM_KEYS: Record<keyof AnalyticsFiltersState, string> = {
  start: 'start',
  end: 'end',
  bucket: 'bucket',
  dataset: 'dataset',
  schema: 'schema',
  workflowId: 'workflow_id',
  pluginId: 'plugin_id',
  status: 'status',
  trigger: 'trigger',
}

/** Last 30 days, all datasets/schemas/workflows/plugins/statuses/triggers. */
export function defaultAnalyticsFilters(now: Date): AnalyticsFiltersState {
  const end = now
  const start = new Date(end.getTime() - DEFAULT_RANGE_DAYS * DAY_MS)
  return {
    start: start.toISOString(),
    end: end.toISOString(),
    bucket: DEFAULT_BUCKET,
    dataset: null,
    schema: null,
    workflowId: null,
    pluginId: null,
    status: null,
    trigger: null,
  }
}

function parseIsoDate(value: string | null): string | null {
  if (!value) return null
  const parsed = new Date(value)
  return isNaN(parsed.getTime()) ? null : parsed.toISOString()
}

function parseBucket(value: string | null): AnalyticsBucket | null {
  return value && (BUCKETS as string[]).includes(value)
    ? (value as AnalyticsBucket)
    : null
}

/** Reads filter state from the URL querystring, falling back to sensible
 * defaults (last 30 days, all datasets) for anything absent or invalid. */
export function parseAnalyticsFilters(
  params: URLSearchParams,
  now: Date,
): AnalyticsFiltersState {
  const defaults = defaultAnalyticsFilters(now)
  return {
    start: parseIsoDate(params.get(PARAM_KEYS.start)) ?? defaults.start,
    end: parseIsoDate(params.get(PARAM_KEYS.end)) ?? defaults.end,
    bucket: parseBucket(params.get(PARAM_KEYS.bucket)) ?? defaults.bucket,
    dataset: params.get(PARAM_KEYS.dataset) || defaults.dataset,
    schema: params.get(PARAM_KEYS.schema) || defaults.schema,
    workflowId: params.get(PARAM_KEYS.workflowId) || defaults.workflowId,
    pluginId: params.get(PARAM_KEYS.pluginId) || defaults.pluginId,
    status: params.get(PARAM_KEYS.status) || defaults.status,
    trigger: params.get(PARAM_KEYS.trigger) || defaults.trigger,
  }
}

/** Applies a partial filter change on top of the current querystring params,
 * writing only the changed keys (`null`/`''` clears a param back to its
 * implicit default) and leaving everything else untouched. */
export function applyAnalyticsFilterPatch(
  params: URLSearchParams,
  patch: Partial<AnalyticsFiltersState>,
): URLSearchParams {
  const next = new URLSearchParams(params)
  for (const key of Object.keys(patch) as (keyof AnalyticsFiltersState)[]) {
    const value = patch[key]
    const paramKey = PARAM_KEYS[key]
    if (value === null || value === undefined || value === '') {
      next.delete(paramKey)
    } else {
      next.set(paramKey, value)
    }
  }
  return next
}

/** Translates filter state into the exact query params every `/analytics/*`
 * endpoint accepts, for widget data hooks to spread onto their requests. */
export function toAnalyticsQueryParams(
  filters: AnalyticsFiltersState,
): URLSearchParams {
  const params = new URLSearchParams()
  params.set(PARAM_KEYS.start, filters.start)
  params.set(PARAM_KEYS.end, filters.end)
  params.set(PARAM_KEYS.bucket, filters.bucket)
  if (filters.dataset) params.set(PARAM_KEYS.dataset, filters.dataset)
  if (filters.schema) params.set(PARAM_KEYS.schema, filters.schema)
  if (filters.workflowId)
    params.set(PARAM_KEYS.workflowId, filters.workflowId)
  if (filters.pluginId) params.set(PARAM_KEYS.pluginId, filters.pluginId)
  if (filters.status) params.set(PARAM_KEYS.status, filters.status)
  if (filters.trigger) params.set(PARAM_KEYS.trigger, filters.trigger)
  return params
}
