import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router'
import type { RecordQueryParams } from '../../api/query'
import type { RecordRef } from '../../api/records'
import type { Schema } from '../../api/schemas'
import type { View } from '../../api/views'
import {
  useRecord,
  useRecordCounts,
  useRecordPage,
} from '../../hooks/useRecords'
import { useSchemas } from '../../hooks/useSchemas'
import { useViews } from '../../hooks/useViews'
import {
  applyExplorerPatch,
  parseExplorerState,
  selectionMatchesView,
  type ExplorerState,
} from '../../utils/explorerState'
import { pruneWireConditions, wireConditions } from '../../utils/filterTree'
import {
  ancestorSchemas,
  defaultColumnNames,
  filterableFields,
  relatedSchemaNames,
  schemasById,
} from '../../utils/hierarchy'
import { collectFields, joinableColumns } from '../../utils/viewFields'
import type { RailLevel } from './HierarchyRail'
import { railLevels } from './railLevels'

const NO_SCHEMAS: Schema[] = []
const NO_VIEWS: View[] = []

export interface ExplorerScope {
  /** Collection to browse; absent = a schema across every collection. */
  dataset?: string
  /** Fixed scope root: only this record's descendants are listed. */
  root?: { id: string }
  /** Schema to list, fixed (no hierarchy rail). */
  lockedSchema?: string
  /** Re-fetch interval, for pages whose records change under running jobs. */
  pollMs?: number | false
}

/** Everything the explorer shows, derived from the URL state plus a handful
 * of queries: which schema is listed, the records in scope, the levels
 * below it with their counts, its saved views, and the columns. The same
 * logic serves a collection, a single record's descendants and a schema
 * browsed across collections -- they differ only in `scope`. */
export function useExplorer(scope: ExplorerScope) {
  const [searchParams, setSearchParams] = useSearchParams()
  const state = useMemo(() => parseExplorerState(searchParams), [searchParams])
  const patch = useCallback(
    (p: Partial<ExplorerState>) =>
      // Moving between levels is a navigation (Back returns to where you
      // were); typing a search or tweaking a filter just refines this one.
      setSearchParams((prev) => applyExplorerPatch(prev, p), {
        replace: !('schema' in p || 'within' in p),
      }),
    [setSearchParams],
  )

  const { data: schemaList } = useSchemas()
  const schemas = schemaList ?? NO_SCHEMAS
  const byId = useMemo(() => schemasById(schemas), [schemas])
  const byName = useMemo(
    () => new Map(schemas.map((s) => [s.name, s])),
    [schemas],
  )

  // --- scope: the record whose descendants are listed, and the path to it
  const rootId = state.within ?? scope.root?.id ?? null
  const { data: scopeRecord } = useRecord(rootId)
  const chain = useMemo<RecordRef[]>(() => {
    if (!scopeRecord) return []
    const full: RecordRef[] = [
      ...(scopeRecord.ancestors ?? []),
      {
        id: scopeRecord.id,
        schema_name: scopeRecord.schema_name,
        natural_name: scopeRecord.natural_name,
      },
    ]
    const start = scope.root
      ? full.findIndex((r) => r.id === scope.root!.id)
      : 0
    return full.slice(Math.max(start, 0))
  }, [scopeRecord, scope.root])
  const scopeSchema = scopeRecord
    ? (byName.get(scopeRecord.schema_name) ?? null)
    : null
  // The hierarchy the rail offers starts below the page's own record (if
  // any), however far down you have drilled.
  const { data: rootRecord } = useRecord(scope.root?.id ?? null)
  const rootSchema = rootRecord
    ? (byName.get(rootRecord.schema_name) ?? null)
    : null

  // --- levels: schemas below the scope with records in it
  const { data: counts } = useRecordCounts(
    scope.dataset ?? '',
    rootId ? { within: rootId } : undefined,
  )
  const levels = useMemo<RailLevel[]>(() => {
    if (scope.lockedSchema) return []
    return railLevels({
      schemas,
      byId,
      rootSchema,
      scopeSchema,
      counts,
      keep: state.schema,
    })
  }, [
    schemas,
    rootSchema,
    scopeSchema,
    byId,
    counts,
    scope.lockedSchema,
    state.schema,
  ])

  const listedName =
    scope.lockedSchema ??
    (state.schema &&
    (levels.length === 0 || levels.some((l) => l.schema.name === state.schema))
      ? state.schema
      : (levels[0]?.schema.name ?? null))
  const listed = listedName ? (byName.get(listedName) ?? null) : null

  // --- what is selected: filter (minus conditions that don't apply at this
  // level), sort, columns
  const related = useMemo(
    () => (listed ? relatedSchemaNames(listed, schemas) : new Set<string>()),
    [listed, schemas],
  )
  const baseFields = useMemo(
    () => (listed ? collectFields(listed, byId) : []),
    [listed, byId],
  )
  const filter = useMemo(
    () =>
      listed
        ? pruneWireConditions(
            state.filter,
            // A condition naming a schema must name one related to this
            // level; a bare one must be a field this level has (a filter
            // made on a selection, unqualified, means nothing on a recording).
            (c) =>
              c.schema
                ? related.has(c.schema)
                : baseFields.some((f) => f.name === c.field),
          )
        : state.filter,
    [state.filter, related, listed, baseFields],
  )
  const ignoredConditions =
    (state.filter ? wireConditions(state.filter).length : 0) -
    (filter ? wireConditions(filter).length : 0)

  const filterFields = useMemo(
    () => (listed ? filterableFields(listed, schemas) : []),
    [listed, schemas],
  )
  const joinable = useMemo(
    () => (listed ? joinableColumns(listed, byId, byName) : []),
    [listed, byId, byName],
  )
  const defaultColumns = useMemo(
    () => (listed ? defaultColumnNames(listed) : []),
    [listed],
  )

  // Sort and columns picked on one level mean nothing on another (a
  // selection's own field can't sort or show recordings -- the API rejects
  // it), so moving levels quietly sets aside whatever doesn't apply here.
  const sort = useMemo(() => {
    if (!listed) return state.sort
    const ownerFields = new Map<string, Set<string>>()
    for (const s of [listed, ...ancestorSchemas(listed, byId)])
      ownerFields.set(s.name, new Set(s.fields.map((f) => f.name)))
    const bare = new Set(baseFields.map((f) => f.name))
    return state.sort.filter((e) =>
      e.schema ? !!ownerFields.get(e.schema)?.has(e.field) : bare.has(e.field),
    )
  }, [state.sort, listed, byId, baseFields])
  const cols = useMemo(() => {
    if (!state.cols || !listed) return state.cols
    const ok = new Set([
      ...baseFields.map((f) => f.name),
      ...joinable.map((j) => j.value),
    ])
    const kept = state.cols.filter((c) => ok.has(c))
    return kept.length > 0 ? kept : null
  }, [state.cols, listed, baseFields, joinable])
  const columnNames = cols ?? defaultColumns

  // --- the query, and its first page
  const query = useMemo<RecordQueryParams>(
    () => ({
      schema: listedName,
      within: rootId,
      search: state.q || undefined,
      filter,
      sort,
    }),
    [listedName, rootId, state.q, filter, sort],
  )
  const page = useRecordPage(
    { datasetName: scope.dataset, schemaName: listedName ?? undefined },
    {
      ...query,
      columns: columnNames,
      child_counts: true,
      limit: state.pageSize,
      offset: state.page * state.pageSize,
    },
    { enabled: !!listedName, refetchInterval: scope.pollMs },
  )

  // --- saved views of the listed schema
  const { data: viewList } = useViews(listedName ?? '')
  const views = viewList ?? NO_VIEWS
  const activeView = views.find((v) => v.name === state.view) ?? null
  const modified = activeView
    ? !selectionMatchesView(
        { ...state, sort, cols },
        activeView,
        defaultColumns,
      )
    : false
  const hasSelection = filter !== null || sort.length > 0 || cols !== null

  return {
    state,
    sort,
    cols,
    patch,
    schemas,
    byId,
    byName,
    rootId,
    chain,
    scopeSchema,
    levels,
    listed,
    listedName,
    filter,
    ignoredConditions,
    filterFields,
    baseFields,
    joinable,
    defaultColumns,
    columnNames,
    query,
    page,
    views,
    viewsLoaded: viewList !== undefined,
    activeView,
    modified,
    hasSelection,
  }
}
