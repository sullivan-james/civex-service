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
import { useFieldTypes } from '../../hooks/useFieldTypes'
import { useStored } from '../../hooks/useStored'
import { useSchemas } from '../../hooks/useSchemas'
import { useViews } from '../../hooks/useViews'
import {
  ALL_KINDS_COLUMNS,
  applyExplorerPatch,
  listsAllKinds,
  parseExplorerState,
  selectionMatchesView,
  type ExplorerState,
} from '../../utils/explorerState'
import type { SortEntry } from '../../api/query'
import { pruneWireConditions, wireConditions } from '../../utils/filterTree'
import {
  ancestorSchemas,
  defaultColumnNames,
  filterableFields,
  relatedSchemaNames,
  schemasById,
} from '../../utils/hierarchy'
import { collectFields, joinableColumns } from '../../utils/viewFields'
import { noteFilterFields } from '../../utils/notes'
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
  // (No collection: every collection; a locked schema has no levels.)
  const { data: counts } = useRecordCounts(
    scope.dataset ?? (scope.lockedSchema ? '' : null),
    rootId ? { within: rootId } : undefined,
  )
  // Until the counts answer there are no levels, which looks like an empty
  // collection; the list waits for them before saying so.
  const countsLoaded = counts !== undefined
  // Every kind at once (`schema=*`, or the open notes on All records): no
  // kind is listed, so only what every record has can filter, sort or show.
  const allKinds = listsAllKinds(state, {
    collection: scope.dataset,
    record: scope.root?.id ?? null,
    locked: !!scope.lockedSchema,
  })
  const levels = useMemo<RailLevel[]>(() => {
    if (scope.lockedSchema) return []
    return railLevels({
      schemas,
      byId,
      rootSchema,
      scopeSchema,
      counts,
      keep: allKinds ? null : state.schema,
    })
  }, [
    schemas,
    rootSchema,
    scopeSchema,
    byId,
    counts,
    scope.lockedSchema,
    state.schema,
    allKinds,
  ])

  const listedName = allKinds
    ? null
    : (scope.lockedSchema ??
      (state.schema &&
      (levels.length === 0 ||
        levels.some((l) => l.schema.name === state.schema))
        ? state.schema
        : (levels[0]?.schema.name ?? null)))
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
      allKinds
        ? // A field belongs to one kind: only what is about the record itself.
          pruneWireConditions(
            state.filter,
            (c) => !c.schema && c.field.startsWith('@'),
          )
        : listed
          ? pruneWireConditions(
              state.filter,
              // A condition naming a schema must name one related to this
              // level; a bare one must be a field this level has (a filter
              // made on a selection, unqualified, means nothing on a recording).
              // Whether a record has open notes means the same on every level.
              (c) =>
                c.schema
                  ? related.has(c.schema)
                  : c.field.startsWith('@') ||
                    baseFields.some((f) => f.name === c.field),
            )
          : state.filter,
    [state.filter, related, listed, baseFields, allKinds],
  )
  const ignoredConditions =
    (state.filter ? wireConditions(state.filter).length : 0) -
    (filter ? wireConditions(filter).length : 0)

  const filterFields = useMemo(
    // Whether a record has open notes, beside its fields.
    () =>
      allKinds
        ? noteFilterFields()
        : listed
          ? [...filterableFields(listed, schemas), ...noteFilterFields()]
          : [],
    [listed, schemas, allKinds],
  )
  const joinable = useMemo(
    () => (listed ? joinableColumns(listed, byId, byName) : []),
    [listed, byId, byName],
  )
  // The columns a person last chose for a kind are remembered in this
  // browser for this project, and are what its lists open with from then on
  // (a saved filter, or `cols` in a link, still says its own).
  const [remembered, setRemembered] = useStored<Record<string, string[]>>(
    'explorer.columns',
    {},
  )
  const chosenColumns = listed ? remembered[listed.name] : undefined
  const defaultColumns = useMemo(() => {
    if (!listed) return []
    const ok = new Set([
      ...baseFields.map((f) => f.name),
      ...joinable.map((j) => j.value),
    ])
    const kept = (chosenColumns ?? []).filter(
      (c) => ok.has(c) || c.startsWith('@'),
    )
    return kept.length > 0 ? kept : defaultColumnNames(listed)
  }, [listed, chosenColumns, baseFields, joinable])
  const rememberColumns = useCallback(
    (cols: string[] | null) => {
      if (!listed) return
      const next = { ...remembered }
      if (cols) next[listed.name] = cols
      else delete next[listed.name]
      setRemembered(next)
    },
    [listed, remembered, setRemembered],
  )

  // Sort and columns picked on one level mean nothing on another (a
  // selection's own field can't sort or show recordings -- the API rejects
  // it), so moving levels quietly sets aside whatever doesn't apply here.
  const sort = useMemo(() => {
    // What every record has (`@kind`, `@collection`, `@updated_at`) sorts
    // any list; a field only its own kind's.
    const meta = (e: SortEntry) => !e.schema && e.field.startsWith('@')
    if (allKinds) return state.sort.filter(meta)
    if (!listed) return state.sort
    const ownerFields = new Map<string, Set<string>>()
    for (const s of [listed, ...ancestorSchemas(listed, byId)])
      ownerFields.set(s.name, new Set(s.fields.map((f) => f.name)))
    const bare = new Set(baseFields.map((f) => f.name))
    return state.sort.filter((e) =>
      meta(e)
        ? true
        : e.schema
          ? !!ownerFields.get(e.schema)?.has(e.field)
          : bare.has(e.field),
    )
  }, [state.sort, listed, byId, baseFields, allKinds])
  const cols = useMemo(() => {
    if (allKinds) return null
    if (!state.cols || !listed) return state.cols
    const ok = new Set([
      ...baseFields.map((f) => f.name),
      ...joinable.map((j) => j.value),
    ])
    const kept = state.cols.filter((c) => ok.has(c))
    return kept.length > 0 ? kept : null
  }, [state.cols, listed, baseFields, joinable, allKinds])
  const columnNames = allKinds ? ALL_KINDS_COLUMNS : (cols ?? defaultColumns)

  // --- the search: every searchable field, or the one picked (kept only
  // while the listed kind has it, like the columns)
  const fieldTypes = useFieldTypes()
  const searchFields = useMemo(() => {
    // Until the field types load (or if they can't), only "every field".
    const types = fieldTypes?.types ?? []
    const searchable = new Set(
      types.filter((t) => t.searchable).map((t) => t.type),
    )
    // Its own fields only: an inherited one's value is the record above's.
    return (listed?.fields ?? []).filter((f) => searchable.has(f.type))
  }, [listed, fieldTypes])
  const searchIn = searchFields.some((f) => f.name === state.qin)
    ? state.qin
    : null

  // --- the query, and its first page
  const query = useMemo<RecordQueryParams>(
    () => ({
      schema: listedName,
      within: rootId,
      search: state.q || undefined,
      search_fields: state.q && searchIn ? [searchIn] : undefined,
      filter,
      sort,
    }),
    [listedName, rootId, state.q, searchIn, filter, sort],
  )
  const page = useRecordPage(
    {
      datasetName: scope.dataset,
      schemaName: listedName ?? undefined,
      allKinds,
    },
    {
      ...query,
      columns: columnNames,
      child_counts: true,
      limit: state.pageSize,
      offset: state.page * state.pageSize,
    },
    { enabled: !!listedName || allKinds, refetchInterval: scope.pollMs },
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
    countsLoaded,
    listed,
    listedName,
    allKinds,
    filter,
    ignoredConditions,
    filterFields,
    baseFields,
    searchFields,
    searchIn,
    joinable,
    defaultColumns,
    /** Whether this kind's columns are a person's own choice, remembered. */
    columnsRemembered: !!chosenColumns,
    rememberColumns,
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
