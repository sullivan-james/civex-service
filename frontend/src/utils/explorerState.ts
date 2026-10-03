/**
 * Everything the record explorer shows is a function of this state, and all
 * of it lives in the URL: a list is linkable, survives a refresh, and "back"
 * undoes a drill-down. Unset values are left out of the querystring so a
 * bookmarked default stays a default.
 */

import type { View } from '../api/views'
import {
  DEFAULT_PAGE_SIZE,
  EMPTY_TABLE_STATE,
  TABLE_RESETS_PAGE,
  parseTableState,
  sameFilter,
  writeTableState,
  type TableState,
} from './tableState'

export { DEFAULT_PAGE_SIZE, sameFilter }

export interface ExplorerState extends TableState {
  /** Schema whose records are listed; null = the first level with records. */
  schema: string | null
  /** Record whose descendants are listed; null = the explorer's own scope. */
  within: string | null
  /** Chosen columns; null = the schema's default columns. */
  cols: string[] | null
  /** Saved view the selection started from (or was saved as). */
  view: string | null
}

export const EMPTY_EXPLORER_STATE: ExplorerState = {
  schema: null,
  within: null,
  cols: null,
  view: null,
  ...EMPTY_TABLE_STATE,
}

export function parseExplorerState(sp: URLSearchParams): ExplorerState {
  return {
    ...parseTableState(sp),
    schema: sp.get('schema') || null,
    within: sp.get('within') || null,
    cols: sp.get('cols') ? sp.get('cols')!.split(',').filter(Boolean) : null,
    view: sp.get('view') || null,
  }
}

/** Anything that changes *which* records match sends the list back to page 1. */
const RESETS_PAGE: (keyof ExplorerState)[] = [
  'schema',
  'within',
  'view',
  ...TABLE_RESETS_PAGE,
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
  for (const key of ['schema', 'within', 'cols', 'view']) out.delete(key)
  if (next.schema) out.set('schema', next.schema)
  if (next.within) out.set('within', next.within)
  if (next.cols) out.set('cols', next.cols.join(','))
  if (next.view) out.set('view', next.view)
  writeTableState(out, next)
  return out
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
