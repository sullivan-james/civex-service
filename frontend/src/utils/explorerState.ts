/**
 * Everything the record explorer shows is a function of this state, and all
 * of it lives in the URL: a list is linkable, survives a refresh, and "back"
 * undoes a drill-down. Unset values are left out of the querystring so a
 * bookmarked default stays a default.
 */

import { decodeSort, encodeSort, type SortEntry } from '../api/query'
import type { View } from '../api/views'
import type { FilterTreeWire } from './filterTree'

export interface ExplorerState {
  /** Schema whose records are listed; null = the first level with records. */
  schema: string | null
  /** Record whose descendants are listed; null = the explorer's own scope. */
  within: string | null
  q: string
  filter: FilterTreeWire | null
  sort: SortEntry[]
  /** Chosen columns; null = the schema's default columns. */
  cols: string[] | null
  /** Saved view the selection started from (or was saved as). */
  view: string | null
  /** 0-based. */
  page: number
  pageSize: number
}

export const DEFAULT_PAGE_SIZE = 50

export const EMPTY_EXPLORER_STATE: ExplorerState = {
  schema: null,
  within: null,
  q: '',
  filter: null,
  sort: [],
  cols: null,
  view: null,
  page: 0,
  pageSize: DEFAULT_PAGE_SIZE,
}

function parseFilter(raw: string | null): FilterTreeWire | null {
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? parsed : null
  } catch {
    return null
  }
}

function positiveInt(raw: string | null): number | null {
  const n = raw == null ? NaN : Number(raw)
  return Number.isInteger(n) && n > 0 ? n : null
}

export function parseExplorerState(sp: URLSearchParams): ExplorerState {
  return {
    schema: sp.get('schema') || null,
    within: sp.get('within') || null,
    q: sp.get('q') ?? '',
    filter: parseFilter(sp.get('filter')),
    sort: sp
      .getAll('sort')
      .map(decodeSort)
      .filter((s): s is SortEntry => s !== null),
    cols: sp.get('cols') ? sp.get('cols')!.split(',').filter(Boolean) : null,
    view: sp.get('view') || null,
    page: (positiveInt(sp.get('page')) ?? 1) - 1,
    pageSize: positiveInt(sp.get('size')) ?? DEFAULT_PAGE_SIZE,
  }
}

/** Anything that changes *which* records match sends the list back to page 1. */
const RESETS_PAGE: (keyof ExplorerState)[] = [
  'schema',
  'within',
  'q',
  'filter',
  'sort',
  'view',
  'pageSize',
]

/** The querystring after applying `patch` to `prev`, leaving unrelated
 * params (e.g. a host page's own) untouched. */
export function applyExplorerPatch(
  prev: URLSearchParams,
  patch: Partial<ExplorerState>,
): URLSearchParams {
  const next: ExplorerState = { ...parseExplorerState(prev), ...patch }
  if (!('page' in patch) && RESETS_PAGE.some((k) => k in patch)) next.page = 0

  const out = new URLSearchParams(prev)
  for (const key of [
    'schema',
    'within',
    'q',
    'filter',
    'sort',
    'cols',
    'view',
    'page',
    'size',
  ])
    out.delete(key)
  if (next.schema) out.set('schema', next.schema)
  if (next.within) out.set('within', next.within)
  if (next.q) out.set('q', next.q)
  if (next.filter) out.set('filter', JSON.stringify(next.filter))
  next.sort.forEach((s) => out.append('sort', encodeSort(s)))
  if (next.cols) out.set('cols', next.cols.join(','))
  if (next.view) out.set('view', next.view)
  if (next.page > 0) out.set('page', String(next.page + 1))
  if (next.pageSize !== DEFAULT_PAGE_SIZE)
    out.set('size', String(next.pageSize))
  return out
}

/** Whether two filter trees are the same selection, ignoring key order. */
export function sameFilter(
  a: FilterTreeWire | null,
  b: FilterTreeWire | null,
): boolean {
  const canon = (v: unknown): unknown =>
    Array.isArray(v)
      ? v.map(canon)
      : v && typeof v === 'object'
        ? Object.fromEntries(
            Object.entries(v as Record<string, unknown>)
              .sort(([x], [y]) => x.localeCompare(y))
              .map(([k, val]) => [k, canon(val)]),
          )
        : v
  return JSON.stringify(canon(a)) === JSON.stringify(canon(b))
}

/** The state a saved view stands for: its filter, sort and columns (none
 * saved = the schema's default columns). */
export function viewPatch(view: View): Partial<ExplorerState> {
  return {
    view: view.name,
    filter: view.filter_tree,
    sort: view.sort,
    cols: view.columns.length > 0 ? view.columns : null,
  }
}

/** Whether the current selection is exactly what `view` saved -- when it
 * isn't, the view is "modified" and can be saved over or saved as new. */
export function selectionMatchesView(
  state: ExplorerState,
  view: View,
  defaultColumns: string[],
): boolean {
  const cols = state.cols ?? defaultColumns
  const viewCols = view.columns.length > 0 ? view.columns : defaultColumns
  return (
    sameFilter(state.filter, view.filter_tree) &&
    JSON.stringify(state.sort) === JSON.stringify(view.sort) &&
    JSON.stringify(cols) === JSON.stringify(viewCols)
  )
}

/** Where a schema's records are browsed across collections, optionally
 * opened on one of its saved views. */
export function schemaRecordsPath(schemaId: string, view?: string): string {
  return `/schemas/${schemaId}/records${view ? `?view=${encodeURIComponent(view)}` : ''}`
}
