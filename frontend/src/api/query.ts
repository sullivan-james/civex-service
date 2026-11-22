/**
 * The record-selection query every list/count/export/delete endpoint shares
 * -- the frontend half of `RecordQuery` (civex/domain/query.py) and its
 * querystring contract (server/query_params.py). One builder, so a filter is
 * serialised the same way wherever it is sent.
 */

import type { FilterTreeWire } from '../utils/filterTree'

export interface SortEntry {
  field: string
  direction: 'asc' | 'desc'
  /** Names an ancestor schema whose field to sort by. */
  schema?: string
}

/** `[schema.]field:direction` -- how a sort travels in a querystring. */
export function encodeSort(s: SortEntry): string {
  return `${s.schema ? `${s.schema}.` : ''}${s.field}:${s.direction}`
}

export function decodeSort(term: string): SortEntry | null {
  const [name, direction = 'asc'] = term.split(':')
  if (!name || (direction !== 'asc' && direction !== 'desc')) return null
  const dot = name.lastIndexOf('.')
  return dot === -1
    ? { field: name, direction }
    : { schema: name.slice(0, dot), field: name.slice(dot + 1), direction }
}

export interface RecordQueryParams {
  schema?: string | null
  /** Only records of `schema` descending (at any depth) from this record. */
  within?: string | null
  /** Direct children only, of any schema. */
  parent_record_id?: string
  search?: string
  /** Look for `search` only in these fields of `schema`. */
  search_fields?: string[]
  /** Legacy `field=value` equality terms. */
  where?: string[]
  filter?: FilterTreeWire | null
  sort?: SortEntry[]
  /** Columns the record's own data can't answer (inherited, joined). */
  columns?: string[]
  child_counts?: boolean
}

export interface PageParams {
  limit?: number
  offset?: number
  /** A previous page's `next_cursor`: keyset paging, which costs the same at
   * any depth and is stable while records change. Replaces `offset`. */
  cursor?: string
  /** Take `total` from the planner's estimate (see `total_estimated`). */
  estimate?: boolean
}

/** `?a=b&…` for the query plus paging, or '' when there is nothing to send. */
export function recordQueryString(
  params: (RecordQueryParams & PageParams) | undefined,
): string {
  if (!params) return ''
  const qs = new URLSearchParams()
  if (params.schema) qs.set('schema', params.schema)
  if (params.within) qs.set('within', params.within)
  if (params.parent_record_id)
    qs.set('parent_record_id', params.parent_record_id)
  if (params.search) qs.set('search', params.search)
  if (params.search)
    params.search_fields?.forEach((f) => qs.append('search_field', f))
  params.where?.forEach((w) => qs.append('where', w))
  if (params.filter) qs.set('filter', JSON.stringify(params.filter))
  params.sort?.forEach((s) => qs.append('sort', encodeSort(s)))
  params.columns?.forEach((c) => qs.append('columns', c))
  if (params.child_counts) qs.set('child_counts', 'true')
  if (params.limit != null) qs.set('limit', String(params.limit))
  if (params.offset != null) qs.set('offset', String(params.offset))
  if (params.cursor) qs.set('cursor', params.cursor)
  if (params.estimate) qs.set('estimate', 'true')
  const query = qs.toString()
  return query ? `?${query}` : ''
}
