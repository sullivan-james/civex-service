/**
 * The part of a list's state every filterable table shares -- search text,
 * AND/OR filter, sort and paging -- and how it lives in the address. The
 * record explorer builds on this (adding schema, scope and columns); the runs
 * and history tables use it as is. `ns` prefixes the parameter names so two
 * tables on one page, or a table under a tab, never read each other's.
 */

import { decodeSort, encodeSort, type SortEntry } from '../api/query'
import type { FilterTreeWire } from './filterTree'

export interface TableState {
  q: string
  filter: FilterTreeWire | null
  sort: SortEntry[]
  /** 0-based. */
  page: number
  pageSize: number
}

export const DEFAULT_PAGE_SIZE = 50

export const EMPTY_TABLE_STATE: TableState = {
  q: '',
  filter: null,
  sort: [],
  page: 0,
  pageSize: DEFAULT_PAGE_SIZE,
}

const KEYS = ['q', 'filter', 'sort', 'page', 'size'] as const

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

export function parseTableState(
  sp: URLSearchParams,
  ns = '',
  defaultPageSize = DEFAULT_PAGE_SIZE,
): TableState {
  return {
    q: sp.get(`${ns}q`) ?? '',
    filter: parseFilter(sp.get(`${ns}filter`)),
    sort: sp
      .getAll(`${ns}sort`)
      .map(decodeSort)
      .filter((s): s is SortEntry => s !== null),
    page: (positiveInt(sp.get(`${ns}page`)) ?? 1) - 1,
    pageSize: positiveInt(sp.get(`${ns}size`)) ?? defaultPageSize,
  }
}

/** Writes `state` into `out` (clearing the table's old values first). Unset
 * values are left out so a bookmarked default stays a default. */
export function writeTableState(
  out: URLSearchParams,
  state: TableState,
  ns = '',
  defaultPageSize = DEFAULT_PAGE_SIZE,
): void {
  for (const key of KEYS) out.delete(`${ns}${key}`)
  if (state.q) out.set(`${ns}q`, state.q)
  if (state.filter) out.set(`${ns}filter`, JSON.stringify(state.filter))
  state.sort.forEach((s) => out.append(`${ns}sort`, encodeSort(s)))
  if (state.page > 0) out.set(`${ns}page`, String(state.page + 1))
  if (state.pageSize !== defaultPageSize)
    out.set(`${ns}size`, String(state.pageSize))
}

/** Changing what matches sends the list back to page 1. */
export const TABLE_RESETS_PAGE: (keyof TableState)[] = [
  'q',
  'filter',
  'sort',
  'pageSize',
]

/** The querystring after applying `patch` to the table state in `prev`,
 * leaving every other parameter alone. */
export function applyTablePatch(
  prev: URLSearchParams,
  patch: Partial<TableState>,
  ns = '',
  defaultPageSize = DEFAULT_PAGE_SIZE,
): URLSearchParams {
  const next = { ...parseTableState(prev, ns, defaultPageSize), ...patch }
  if (!('page' in patch) && TABLE_RESETS_PAGE.some((k) => k in patch))
    next.page = 0
  const out = new URLSearchParams(prev)
  writeTableState(out, next, ns, defaultPageSize)
  return out
}

/** Click-through order for a column header: ascending, descending, off. */
export function nextSort(current: SortEntry[], key: string): SortEntry[] {
  const cur = current[0]
  if (!cur || cur.field !== key) return [{ field: key, direction: 'asc' }]
  if (cur.direction === 'asc') return [{ field: key, direction: 'desc' }]
  return []
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
