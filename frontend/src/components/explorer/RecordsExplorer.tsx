import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router'
import {
  useDeleteManyRecords,
  useDeleteMatchingRecords,
  useRecordQuality,
  useRecordSummary,
} from '../../hooks/useRecords'
import { queryBody } from '../../api/records'
import {
  useCreateView,
  useDeleteView,
  useUpdateView,
} from '../../hooks/useViews'
import {
  Button,
  Chip,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Input,
  Pagination,
  Menu,
  PinButton,
  type MenuEntry,
  type MenuItem,
  TriggerPopover,
  TableSkeleton,
  Field,
  Select,
  Skeleton,
  SplitPane,
  Subheading,
} from '../ui'
import {
  AlertTriangle,
  PanelRightOpen,
  ChevronDown,
  Columns3,
  Plus,
} from '../ui/icons'
import { toTableRows } from '../records/tableRows'
import {
  RecordsTable,
  type RecordsTableRow,
  type RecordsTableSort,
} from '../records/RecordsTable'
import { ColumnPicker, columnLabel } from '../views/ColumnPicker'
import { OPEN_NOTES_FILTER, asksForOpenNotes } from '../../utils/notes'
import { FilterControls } from './FilterControls'
import { DrillLinks } from './DrillLinks'
import { SavedViewBar } from './SavedViewBar'
import { ScopeTrail, type TrailItem } from './ScopeTrail'
import { SelectionBar } from './SelectionBar'
import { MoveRecordsDialog } from './MoveRecordsDialog'
import { BulkEditDialog } from './BulkEditDialog'
import { bulkEditableFields } from '../../utils/bulkEdit'
import { FilesView } from '../files/FilesView'
import type { View } from '../../api/views'
import { SAVED_KINDS } from '../../utils/savedKinds'
import { ChecksView } from './ChecksView'
import { withCondition } from '../../utils/summary'
import { ChartsColumn } from './ChartsColumn'
import { useExplorerCharts } from './useExplorerCharts'
import { OpenChart } from '../charts/ChartBoard'
import { NewChart } from '../charts/NewChart'
import { downloadCharts } from '../charts/downloadCharts'
import { useToast } from '../ui/ToastProvider'
import { CHARTS_AUTO_UP_TO, chartTitle, plural } from '../../utils/charts'
import { totalsCells, totalsMeasures } from '../../utils/totals'
import { useStored } from '../../hooks/useStored'
import { MoveToDriveButton } from '../files/MoveDialog'
import { useBulkSelection } from '../../hooks/useBulkSelection'
import { BulkRunWorkflow, bulkRunnable } from '../workflows/BulkRunWorkflow'
import { FileAccessActions } from '../files/FileAccessActions'
import { selectionFor } from '../../api/fileAccess'
import { useAvailableExports } from '../../hooks/useExportDefinitions'
import { describeDefinition } from '../../utils/exportBuilder'
import { schemaTreeHasFiles } from '../../utils/hierarchy'
import { useWorkflows } from '../../hooks/useWorkflows'
import { useExplorer, type ExplorerScope } from './useExplorer'
import { useCollection } from '../../hooks/useCollections'
import { usePermissions } from '../../hooks/useMe'
import { EmptyCollectionGuide } from './EmptyCollectionGuide'
import { recordRecent } from '../../hooks/usePins'
import { placeTarget, viewTarget } from '../../utils/navTargets'
import type { NavTarget } from '../../utils/pins'
import { applyExplorerPatch, viewPatch } from '../../utils/explorerState'
import { ancestorSchemas } from '../../utils/hierarchy'
import { HIGH_IMPACT_RECORD_THRESHOLD } from '../../lib/deleteImpact'
import { errorMessage } from '../../lib/errors'
import { pluralise } from '../../lib/utils'
import { displayLabel } from '../../utils/naming'

/** A kind's display name, for a chart's title. */
const listedLabelOf = (
  listed: { name: string; label: string | null } | null | undefined,
) => (listed ? displayLabel(listed.name, listed.label) : '')

/** What the explorer shows of a list: its records, its charts, or both. */
type ExplorerLayout = 'records' | 'both' | 'charts'

/** Past this many listed records, the data check is not run just to count
 * (it reads every record): the count waits until Checks is opened. */
const CHECK_COUNT_UP_TO = 5000

export interface RecordsExplorerProps extends ExplorerScope {
  /** Shown as the first crumb when browsing a whole collection. */
  scopeLabel?: string
  /** Extra buttons on the toolbar (e.g. Import). */
  toolbarActions?: ReactNode
  /** Shown instead of the table when there is nothing in scope at all. */
}

/** The one way records are browsed: a collection, a single record's
 * descendants at any depth, or a schema across collections. A hierarchy rail
 * picks the level, a trail shows where you are, search + filters + saved
 * filters narrow it, and every row links down to its children. All state is
 * in the URL. */
/** The columns of what every record has, which a list of every kind shows
 * (`ALL_KINDS_COLUMNS`) and any list can sort by. */
const META_COLUMNS: Record<string, { label: string; type: string }> = {
  '@kind': { label: 'Kind', type: 'kind' },
  '@collection': { label: 'Collection', type: 'collection' },
  '@updated_at': { label: 'Last edited', type: 'updated' },
}

/** Why something about one kind's fields is switched off in a list of every
 * kind. */
function pickKind(what: string): string {
  return `Pick a kind of record to ${what}`
}

export function RecordsExplorer({
  scopeLabel,
  toolbarActions,
  ...scope
}: RecordsExplorerProps) {
  const x = useExplorer(scope)
  const { state, patch, listed, listedName, allKinds } = x
  const dataset = scope.dataset
  // Shown under a record's fields ("Inside this …"): a quieter explorer.
  const inside = !!scope.root
  const { data: collection } = useCollection(dataset ?? '')
  const location = useLocation()

  // --- search box: local text, pushed to the URL after a pause
  const [searchInput, setSearchInput] = useState(state.q)
  const [seenQ, setSeenQ] = useState(state.q)
  if (state.q !== seenQ) {
    setSeenQ(state.q)
    setSearchInput(state.q)
  }
  useEffect(() => {
    if (searchInput === state.q) return
    const t = setTimeout(() => patch({ q: searchInput }), 300)
    return () => clearTimeout(t)
  }, [searchInput, state.q, patch])

  // --- selection (only where rows can be deleted)
  const picked = useBulkSelection(
    (x.page.data?.items ?? []).map((r) => r.id),
    JSON.stringify([listedName, x.rootId, x.query, state.page, state.pageSize]),
  )
  const { selected, allMatching } = picked
  // The same records, as their files (and those of everything beneath them):
  // one set of filters for both, held in the address like the rest.
  const [params, setParams] = useSearchParams()
  const show = params.get('show')
  const showFiles = show === 'files'
  /** Open a saved filter: its filter, sort and columns. */
  const openView = (v: View) => patch(viewPatch(v))
  // --- `?view=name` in a shared link: apply it once, when nothing else was
  // chosen. Only ever on arrival -- afterwards the URL is the truth, so
  // clearing the filter of a saved filter stays cleared.
  const seededView = useRef(false)
  useEffect(() => {
    if (seededView.current || !x.viewsLoaded) return
    seededView.current = true
    const v = x.activeView
    if (!v || x.hasSelection) return
    patch(viewPatch(v))
  }, [x.viewsLoaded, x.activeView, x.hasSelection, patch])

  // What in the listed records needs a look (`ChecksView`).
  const showChecks = show === 'checks' && !!listed
  const setShow = (v: string | null) =>
    setParams(
      (prev) => {
        const out = new URLSearchParams(prev)
        if (v === null) out.delete('show')
        else out.set('show', v)
        return out
      },
      { replace: true },
    )
  // How many listed records have something to look at: the data check reads
  // every listed record, so it is asked by itself only for a list up to
  // CHECK_COUNT_UP_TO records; a bigger one is counted once Checks is opened.
  // Shared with ChecksView (the same query, under `records`, so an edit
  // counts again).
  const listedTotal = x.page.data?.total ?? 0
  const checkCount = useRecordQuality(
    listed &&
      !x.page.error &&
      x.page.data !== undefined &&
      // Not counted under a record's fields, where it isn't shown.
      (showChecks || (!inside && listedTotal <= CHECK_COUNT_UP_TO))
      ? queryBody({ ...x.query, sort: undefined }, dataset)
      : null,
  )
  const issuesFound = checkCount.data?.records_with_issues
  // --- charts: beside the records, counting exactly what is listed. They
  // are asked for once the rows are in, and a very big list waits for a click.
  const records = queryBody({ ...x.query, sort: undefined }, dataset)
  // Whether charts are beside the records, remembered in this browser for
  // this project (not, to start with, on a narrow screen). `charts` is the
  // charts at full width: a screen over the same records, with a way back.
  const [layout, setLayout] = useStored<ExplorerLayout>(
    'explorer.layout',
    typeof window !== 'undefined' && window.innerWidth < 1024
      ? 'records'
      : 'both',
  )
  // Under a record's own fields the page is just the rows: no charts there.
  const chartsHidden = inside || layout === 'records'
  const chartsOnly = !inside && layout === 'charts' && !!listed
  const [chartsAsked, setChartsAsked] = useState(false)
  // Problems and files are screens of their own over the same records:
  // the charts, which count records, step aside.
  const aside = showChecks || showFiles
  const rowsIn = x.page.data !== undefined && !x.page.error
  const chartsOn = rowsIn && (listedTotal <= CHARTS_AUTO_UP_TO || chartsAsked)
  const charts = useExplorerCharts(listed ?? null, x.filterFields)
  const setFilter = (filter: typeof x.filter) => patch({ filter })
  // The charts on screen go out with Export too: their numbers, a table
  // each (a map has none).
  const toast = useToast()
  const exportable = charts.charts
    .filter((c) => !c.map)
    .map((chart) => ({
      chart,
      title: chartTitle(chart, charts.usable, listedLabelOf(listed), x.schemas),
    }))
  const sendCharts = (which: typeof exportable) =>
    downloadCharts(which, records, 'csv').catch((e) =>
      toast.error(errorMessage(e)),
    )
  const chartItems: MenuEntry[] =
    listed && exportable.length > 0
      ? [
          { heading: 'Charts' },
          ...(exportable.length > 1
            ? [
                {
                  label: `All ${exportable.length} charts`,
                  onClick: () => sendCharts(exportable),
                },
              ]
            : []),
          ...exportable.map((c) => ({
            label: c.title,
            onClick: () => sendCharts([c]),
          })),
        ]
      : []
  // --- totals under the table, for every record listed.
  const totalsAsk = listed ? totalsMeasures(x.columnNames, listed.fields) : []
  const totals = useRecordSummary(
    rowsIn && !inside && totalsAsk.length > 0 && listedTotal > 0
      ? { ...records, group_by: [], measures: totalsAsk }
      : null,
  )
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [moving, setMoving] = useState(false)
  const [editing, setEditing] = useState(false)
  const deleteMany = useDeleteManyRecords(dataset ?? '')
  const deleteMatching = useDeleteMatchingRecords(dataset ?? '')
  const createView = useCreateView(listedName ?? '')
  const updateView = useUpdateView(listedName ?? '', x.activeView?.name ?? '')
  const deleteView = useDeleteView(listedName ?? '')

  // Whether the listed records can hold files at all, and what to call the
  // folder their files are opened in: the same view gives the same folder.
  // Whether the listed records, or anything beneath them, can hold files: an
  // Encounter holds none itself but its Recordings and Selections do, so its list
  // still offers the files (everything beneath each record listed).
  const canExportFiles = !!x.listed && schemaTreeHasFiles(x.listed, x.schemas)
  const hasFiles = x.baseFields.some(
    (f) => f.type === 'file' || f.type === 'file_list',
  )
  // The exports saved with the listed kind of record (or one above it), and where
  // to set more up.
  const { data: savedExports } = useAvailableExports(
    listedName ? { schema: listedName } : null,
  )
  const exportPresets = (savedExports ?? []).map((d) => ({
    label: d.name,
    hint: describeDefinition(d, x.schemas),
    selection: {
      export: `${d.schema_name}/${d.name}`,
      collection: dataset,
      within: x.rootId ?? undefined,
    },
    folderName: [dataset, d.name].filter(Boolean).join('-'),
    definition: d,
  }))
  const builderHref = x.listed
    ? `/exports?schema=${encodeURIComponent(x.listed.name)}`
    : undefined
  const folderName = [dataset, listedName, x.rootId?.slice(0, 8)]
    .filter(Boolean)
    .join('-')

  const items = x.page.data?.items ?? []
  const total = x.page.data?.total ?? 0
  // How many of the kind there are here before the filter and search.
  const inScope =
    listed && (x.filter || state.q)
      ? (x.levels.find((l) => l.schema.id === listed.id)?.count ?? null)
      : null
  const rows = toTableRows(items)
  // Listing records with open notes (the "Open notes" view): the column says
  // what is open, and a record opens on its Notes tab.
  const openNotesView = asksForOpenNotes(x.filter)
  const columnNames =
    openNotesView && !x.columnNames.includes(OPEN_NOTES_FILTER)
      ? [...x.columnNames, OPEN_NOTES_FILTER]
      : x.columnNames
  const columns = columnNames.map((name) => {
    if (name === OPEN_NOTES_FILTER)
      return { name, label: 'Open notes', type: 'notes', sortable: false }
    const meta = META_COLUMNS[name]
    if (meta) return { name, label: meta.label, type: meta.type }
    const field = x.baseFields.find((f) => f.name === name)
    return {
      name,
      label: columnLabel(name, x.baseFields, x.joinable),
      // A formula's cells are of the type it gives; a list can't be sorted
      // by it (worked out when read, so the database holds nothing to order).
      type:
        field?.type === 'formula'
          ? String(field.restrictions?.result ?? 'string')
          : field?.type,
      sortable: !name.includes('.') && field?.type !== 'formula',
    }
  })
  const sort: RecordsTableSort | undefined = x.sort[0]
    ? { key: x.sort[0].field, direction: x.sort[0].direction }
    : undefined

  function toggleSort(key: string) {
    const cur = x.sort[0]
    if (!cur || cur.field !== key)
      patch({ sort: [{ field: key, direction: 'asc' }] })
    else if (cur.direction === 'asc')
      patch({ sort: [{ field: key, direction: 'desc' }] })
    else patch({ sort: [] })
  }

  // --- moving through the hierarchy
  const scopeRootId = scope.root?.id ?? null
  function goToRecord(index: number) {
    const record = x.chain[index]
    const next = x.chain[index + 1]
    patch({
      within: record.id === scopeRootId ? null : record.id,
      schema: next?.schema_name ?? listedName,
      q: '',
    })
  }
  function pickLevel(schemaName: string) {
    const target = x.byName.get(schemaName)
    if (!target) return
    const above = new Set(ancestorSchemas(target, x.byId).map((s) => s.id))
    const holder = [...x.chain]
      .reverse()
      .find((r) => above.has(x.byName.get(r.schema_name)?.id ?? ''))
    patch({
      schema: schemaName,
      within: holder && holder.id !== scopeRootId ? holder.id : null,
      q: '',
    })
  }
  function drill(row: RecordsTableRow, childSchema: string) {
    patch({ within: row.id, schema: childSchema, q: '' })
  }

  const trail: TrailItem[] = []
  if (!scope.root && x.chain.length > 0 && scopeLabel)
    trail.push({
      key: 'collection',
      label: scopeLabel,
      onClick: () =>
        patch({ within: null, schema: x.chain[0].schema_name, q: '' }),
    })
  x.chain.forEach((r, i) =>
    trail.push({
      key: r.id,
      label: r.natural_name ?? r.id.slice(0, 8),
      onClick:
        i === x.chain.length - 1 && !state.within
          ? undefined
          : () => goToRecord(i),
    }),
  )

  // What an export from here starts as: the rows and columns shown, in their
  // order, as a table; and the files too where this kind of record has any.
  const exportContext = (ids?: string[]) => ({
    ...selectionFor(x.query, dataset, ids, x.activeView?.files_layout, true),
    sort: x.sort,
    tables: [
      {
        format: 'csv' as const,
        // What every record has (its kind, open notes) is shown, not
        // written in a table: a list of every kind writes one per kind.
        columns: x.columnNames.filter((c) => !c.startsWith('@')),
        kind: x.listed?.name ?? null,
      },
    ],
    // A list exports as the table of what is shown; files are added from there.
    files: false,
  })

  const parentIsRoot =
    listed && x.scopeSchema && listed.parent_id === x.scopeSchema.id
  // A new record of the listed schema, under the record being browsed when
  // that is its parent.
  const newRecordHref = `/collections/${dataset}/new?${new URLSearchParams({
    ...(listed ? { schema: listed.name } : {}),
    ...(parentIsRoot && x.rootId ? { parent: x.rootId } : {}),
  })}`
  const bulkCount = allMatching ? total : selected.size
  const { data: allWorkflows } = useWorkflows()
  const runnable = listed ? bulkRunnable(allWorkflows, listed.name) : []
  const listedLabel = listed
    ? displayLabel(listed.name, listed.label)
    : allKinds
      ? 'Record'
      : ''

  // What the star pins: the saved filter when one is applied as saved,
  // otherwise this place in the explorer exactly as the address bar has it.
  const placeLabel = [
    listedLabel,
    x.chain.length > 0 &&
      `in ${x.chain[x.chain.length - 1].natural_name ?? x.chain[x.chain.length - 1].id.slice(0, 8)}`,
    state.q && `matching “${state.q}”`,
  ]
    .filter(Boolean)
    .join(' ')
  const pinTarget: NavTarget | null =
    listed && x.activeView && !x.modified
      ? viewTarget(listed, x.activeView.name)
      : listed
        ? placeTarget(
            location.pathname + location.search,
            placeLabel,
            dataset ?? 'All collections',
          )
        : null

  // Opening a saved filter or a drilled-down place counts as visiting it.
  const recentKey = pinTarget?.key
  const recentLabel = pinTarget?.label
  useEffect(() => {
    if (!pinTarget || !listed) return
    // A plain, un-drilled list is just the collection or schema page again.
    if (
      pinTarget.kind === 'place' &&
      !state.within &&
      !state.q &&
      !x.hasSelection
    )
      return
    recordRecent(pinTarget)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recentKey, recentLabel])

  function confirmBulkDelete() {
    const done = {
      onSuccess: () => {
        picked.clear()
        setConfirmDelete(false)
      },
    }
    if (allMatching) deleteMatching.mutate(x.query, done)
    else deleteMany.mutate([...selected], done)
  }

  // The top-level schemas: where a record can start. Levels come from record
  // counts, so a schema with no records yet has none, and without these there
  // would be no way to create the first of its kind. A collection holds
  // records of every schema.
  const navigate = useNavigate()
  // What this person may do here: the controls stay, off, saying why.
  const { can, why } = usePermissions()
  const mayWrite = can('write_records', collection?.id)
  const mayDelete = can('delete', collection?.id)
  const starters = dataset ? (x.schemas ?? []).filter((s) => !s.parent_id) : []
  // At the top of a collection, the starters other than the one being listed.
  const otherStarters = x.rootId
    ? []
    : starters.filter((s) => s.name !== listed?.name)
  // Inside a record, what can be made under it: the schemas that are children
  // of its own, whether or not it has any yet (levels come from record counts,
  // so a recording with no selections lists nothing, and without these there
  // would be no way to add its first one).
  const childStarters =
    dataset && x.rootId && x.scopeSchema
      ? (x.schemas ?? []).filter(
          (s) => s.parent_id === x.scopeSchema!.id && s.name !== listed?.name,
        )
      : []

  // One way to create anything: a single New menu. What is being listed comes
  // first (under the record being browsed when that is its parent), then the
  // other places a record can start, then import.
  const newItems: MenuItem[] = dataset
    ? [
        ...(listed
          ? [
              {
                label: `New ${listedLabel.toLowerCase()}`,
                icon: Plus,
                onClick: () => navigate(newRecordHref),
              },
            ]
          : []),
        ...childStarters.map((s) => ({
          label: `New ${displayLabel(s.name, s.label).toLowerCase()}`,
          icon: Plus,
          onClick: () =>
            navigate(
              `/collections/${dataset}/new?${new URLSearchParams({ schema: s.name, parent: x.rootId! })}`,
            ),
        })),
        ...otherStarters.map((s) => ({
          label: `New ${displayLabel(s.name, s.label).toLowerCase()}`,
          icon: Plus,
          onClick: () =>
            navigate(
              `/collections/${dataset}/new?${new URLSearchParams({ schema: s.name })}`,
            ),
        })),
      ]
    : []
  const newMenu =
    newItems.length > 0 &&
    (mayWrite ? (
      <Menu
        items={newItems}
        trigger={({ open, toggle }) => (
          <Button
            variant="primary"
            size="sm"
            aria-haspopup="menu"
            aria-expanded={open}
            onClick={toggle}
          >
            <Plus size={14} /> New <ChevronDown size={14} />
          </Button>
        )}
      />
    ) : (
      <Button variant="primary" size="sm" disabled title={why('write_records')}>
        <Plus size={14} /> New <ChevronDown size={14} />
      </Button>
    ))

  // Which columns: a choice about the records, so it sits beside their count. A
  // list of every kind shows what every record has (no choice).
  const columnsButton = !allKinds && (
    <TriggerPopover
      label="Choose columns"
      align="right"
      panelClassName="w-[28rem] max-w-[90vw]"
      trigger={({ toggle, open }) => (
        <Button size="sm" onClick={toggle} aria-expanded={open}>
          <Columns3 size={14} /> Columns
        </Button>
      )}
    >
      <ColumnPicker
        columns={x.columnNames}
        onChange={(cols) => patch({ cols })}
        baseFields={x.baseFields}
        joinable={x.joinable}
        extra={[{ name: OPEN_NOTES_FILTER, label: 'Open notes' }]}
        allowHideAll={false}
      />
      {x.cols && (
        <Button
          size="sm"
          variant="ghost"
          className="mt-2"
          onClick={() => patch({ cols: null })}
        >
          Reset to default columns
        </Button>
      )}
    </TriggerPopover>
  )

  const kindsInside = x.levels.filter((l) => (l.count ?? 0) > 0)

  // Until the collection and its counts have answered, nothing is listed and
  // there is no New: a menu opened now would be replaced by the loaded one.
  if (!listed && !allKinds && (!x.countsLoaded || (dataset && !collection)))
    return <Skeleton className="h-32 w-full" />

  if (!listed && !allKinds && !x.page.isLoading && x.levels.length === 0) {
    // Levels come from record counts, so an empty collection has none and the
    // list's own "Add" button never renders -- offer the collection's own
    // top-level schemas here instead, or there is no way to create the first
    // record (a child schema needs a parent record, so it can't start one).
    return (
      <EmptyCollectionGuide
        collection={dataset ? collection : null}
        schemas={x.schemas ?? []}
        within={
          x.rootId && x.scopeSchema
            ? { id: x.rootId, schema: x.scopeSchema }
            : null
        }
        newMenu={newMenu}
        cannotAddSchema={
          can('change_structure') ? undefined : why('change_structure')
        }
      />
    )
  }

  return (
    <div>
      <div className="min-w-0 space-y-3">
        <ScopeTrail items={trail} heading={listedLabel} />
        {inside && kindsInside.length > 1 && (
          // What is inside, a kind at a time: one click each.
          <div className="flex flex-wrap gap-2" aria-label="Kinds inside">
            {kindsInside.map((l) => (
              <Chip
                key={l.schema.id}
                selected={l.schema.id === listed?.id}
                onClick={() => pickLevel(l.schema.name)}
              >
                {displayLabel(l.schema.name, l.schema.label)}
                <span className="text-xs font-normal opacity-70">
                  {(l.count ?? 0).toLocaleString()}
                </span>
              </Chip>
            ))}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <div className="min-w-[14rem] max-w-xl flex-1">
            <Field label="Search records" hideLabel>
              <Input
                type="search"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder={
                  showFiles
                    ? 'Search files…'
                    : `Search ${listedLabel.toLowerCase() || 'records'}…`
                }
                className="w-full"
              />
            </Field>
          </div>
          {!inside && !showFiles && x.searchFields.length > 1 && (
            // Which field the search looks in: every one, or just one.
            <Field label="Search in" hideLabel>
              <Select
                aria-label="Search in"
                value={x.searchIn ?? ''}
                onChange={(e) => patch({ qin: e.target.value || null })}
              >
                <option value="">In all fields</option>
                {x.searchFields.map((f) => (
                  <option key={f.name} value={f.name}>
                    In {displayLabel(f.name, f.label)}
                  </option>
                ))}
              </Select>
            </Field>
          )}
          <div className="ml-auto flex flex-wrap items-center gap-2">
            {toolbarActions}
            {/* The record's own page has its star. */}
            {pinTarget && !inside && (
              <PinButton
                target={pinTarget}
                noun={
                  pinTarget.saved
                    ? SAVED_KINDS[pinTarget.saved].word.toLowerCase()
                    : 'place'
                }
                size="md"
              />
            )}
            {newMenu}
          </div>
        </div>

        {/* The view's own controls: which rows (saved filters and the conditions
            below), which columns, and Export of what that leaves. Inside a
            record's page they are a step away (Open as a list). */}
        <div
          className={`flex flex-wrap items-start gap-2 ${inside ? 'hidden' : ''}`}
        >
          <div className="min-w-0 flex-1">
            {/* A saved filter belongs to one kind of record. */}
            {!allKinds && (
              <SavedViewBar
                views={x.views}
                activeView={x.activeView}
                modified={x.modified}
                hasSelection={x.hasSelection}
                onApply={openView}
                onClear={() =>
                  patch({ view: null, filter: null, sort: [], cols: null })
                }
                onSave={() =>
                  updateView.mutate({
                    columns: x.columnNames,
                    filter_tree: x.filter,
                    sort: x.sort,
                  })
                }
                onSaveAs={(name, done) =>
                  createView.mutate(
                    {
                      name,
                      columns: x.columnNames,
                      filter_tree: x.filter,
                      sort: x.sort,
                    },
                    {
                      onSuccess: (created) => {
                        done()
                        patch({ view: created.name })
                      },
                    },
                  )
                }
                onRename={(name, done) =>
                  updateView.mutate(
                    { rename: name },
                    {
                      onSuccess: (updated) => {
                        done()
                        patch({ view: updated.name })
                      },
                    },
                  )
                }
                onDelete={(done) =>
                  deleteView.mutate(x.activeView!.name, {
                    onSuccess: () => {
                      done()
                      patch({ view: null })
                    },
                  })
                }
                filesLayout={hasFiles ? x.activeView?.files_layout : undefined}
                onFilesLayout={
                  hasFiles && x.activeView
                    ? (files_layout) => updateView.mutate({ files_layout })
                    : undefined
                }
                pending={
                  createView.isPending ||
                  updateView.isPending ||
                  deleteView.isPending
                }
                error={createView.error ?? updateView.error ?? deleteView.error}
              />
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <FileAccessActions
              label="Export"
              selection={exportContext()}
              folderName={folderName}
              presets={canExportFiles ? exportPresets : []}
              scopeSchema={listedName ?? undefined}
              builderTo={builderHref}
              leading={chartItems}
            />
          </div>
        </div>

        {(listed || allKinds) && (!inside || x.filter) && (
          <FilterControls
            wire={x.filter}
            fields={x.filterFields}
            listedSchema={listed?.name ?? ''}
            records={listed ? records : undefined}
            onChange={(filter) => patch({ filter })}
          />
        )}
        {x.ignoredConditions > 0 && (
          <p className="text-xs text-fg-muted">
            {pluralise(x.ignoredConditions, 'filter')} not used here
          </p>
        )}

        {(charts.building || charts.editing) && listed && !aside && (
          <NewChart
            // A fresh builder for each chart it is opened on.
            key={charts.editing?.id ?? 'new'}
            listed={listed}
            schemas={x.schemas}
            usable={charts.usable}
            kind={listedLabel}
            records={records}
            initial={charts.editing ?? undefined}
            onAdd={charts.keep}
            onCancel={() => charts.setOpen(null)}
          />
        )}
        {charts.open && listed && !aside && (
          <OpenChart
            chart={charts.open}
            title={chartTitle(
              charts.open,
              charts.usable,
              listedLabel,
              x.schemas,
            )}
            records={records}
            usable={charts.usable}
            onFilter={setFilter}
            onClose={() => charts.setOpen(null)}
          />
        )}

        {/* A rule sets the results apart from the filters above. */}
        <div className="flex items-start gap-2 border-t border-border pt-4">
          <div className="min-w-0 flex-1">
            <SplitPane
              storageKey="explorer.charts.width"
              label="Charts"
              // Charts alone: the records step aside (the count stays above).
              sideOnly={chartsOnly && !aside}
              side={
                chartsHidden || aside || x.page.error ? undefined : listed ? (
                  <ChartsColumn
                    model={charts}
                    listed={listed}
                    schemas={x.schemas}
                    kind={listedLabel}
                    records={records}
                    scope={{
                      collection: collection?.id ?? null,
                      within: x.rootId ?? null,
                    }}
                    onFilter={setFilter}
                    enabled={chartsOn}
                    onShow={() => setChartsAsked(true)}
                    onExpand={
                      chartsOnly ? undefined : () => setLayout('charts')
                    }
                    onCollapse={
                      chartsOnly ? undefined : () => setLayout('records')
                    }
                    onBack={chartsOnly ? () => setLayout('both') : undefined}
                  />
                ) : undefined
              }
              main={
                <div className="min-w-0 space-y-3">
                  {!x.page.error && (
                    // The records' own heading: how many, and what is about them. It
                    // is level with the charts panel's heading beside it.
                    <div className="flex min-h-9 flex-wrap items-center gap-3">
                      {showFiles ? (
                        // The files of what is listed: an occasional job (moving,
                        // downloading), reached from the page's menu, not a peer of
                        // the records.
                        <Subheading as="h2">Files</Subheading>
                      ) : (
                        <p className="text-base" aria-live="polite">
                          <span className="font-semibold text-fg">
                            {total.toLocaleString()}
                          </span>{' '}
                          {inScope !== null && inScope !== total && (
                            <>of {inScope.toLocaleString()} </>
                          )}
                          {total === 1
                            ? listedLabel.toLowerCase()
                            : plural(listedLabel)}
                        </p>
                      )}
                      {listed &&
                        !inside &&
                        !!issuesFound &&
                        !showChecks &&
                        !showFiles && (
                          // A fact beside the count: nothing is shown when all is well.
                          <Button
                            size="sm"
                            variant="link"
                            onClick={() => setShow('checks')}
                          >
                            <AlertTriangle
                              size={14}
                              className="text-attention"
                            />
                            {issuesFound.toLocaleString()}{' '}
                            {issuesFound === 1 ? 'problem' : 'problems'}
                          </Button>
                        )}
                      {/* Beside the count of the records whose columns they are. */}
                      {!inside && !aside && !chartsOnly && columnsButton}
                      {(showChecks || showFiles) && (
                        <Button
                          size="sm"
                          variant="link"
                          onClick={() => setShow(null)}
                        >
                          Back to records
                        </Button>
                      )}
                      <div className="ml-auto flex items-center gap-2">
                        {chartsHidden && listed && !aside && !inside && (
                          // Folded away: the way back says what it opens, at
                          // the right-hand edge of the table.
                          <Button size="sm" onClick={() => setLayout('both')}>
                            <PanelRightOpen size={14} /> Charts
                          </Button>
                        )}
                        {inside && listed && collection && !aside && (
                          // Everything else a list can do (filters, charts,
                          // columns, export, ticking rows) is one step away,
                          // on the same records.
                          <Button
                            size="sm"
                            variant="ghost"
                            to={`/collections/${collection.id}?${new URLSearchParams(
                              {
                                schema: listed.name,
                                ...(x.rootId ? { within: x.rootId } : {}),
                              },
                            )}`}
                          >
                            Open as a list
                          </Button>
                        )}
                      </div>
                    </div>
                  )}

                  {showChecks && listed ? (
                    <ChecksView
                      query={x.query}
                      collection={dataset}
                      listed={listed}
                      mayWrite={mayWrite}
                      cannotWrite={why('write_records')}
                      // The records: the condition added to the filter, listed, in one
                      // change to the address (as a summary's group).
                      onDrill={(where) =>
                        setParams((prev) => {
                          const out = applyExplorerPatch(prev, {
                            filter: withCondition(x.filter, where),
                          })
                          out.delete('show')
                          return out
                        })
                      }
                    />
                  ) : showFiles ? (
                    <FilesView
                      // The search box looks for files here (their names, and the
                      // records they sit under), not for the records listed above them.
                      // Inside a record, its own files are among "their files" too.
                      // With no record chosen and no filter, they are every file here
                      // (the collection's, or every collection's), whatever level the
                      // rail shows: a kind of record narrows only what is filtered.
                      selection={{
                        ...selectionFor(
                          {
                            ...x.query,
                            search: undefined,
                            schema:
                              x.query.within || x.filter
                                ? x.query.schema
                                : undefined,
                          },
                          dataset,
                          undefined,
                          undefined,
                          true,
                        ),
                        with_within: !!x.query.within,
                      }}
                      search={state.q || undefined}
                    />
                  ) : (
                    <>
                      {dataset && (
                        <SelectionBar
                          selectedCount={selected.size}
                          pageCount={rows.length}
                          total={total}
                          allMatching={allMatching}
                          onSelectAllMatching={picked.selectAllMatching}
                          onDelete={() => setConfirmDelete(true)}
                          cannotDelete={mayDelete ? undefined : why('delete')}
                          deleting={
                            deleteMany.isPending || deleteMatching.isPending
                          }
                          // Runs are queued for the records ticked, not for "all matching":
                          // that would be every record the filters match, on every page.
                          actions={
                            <>
                              <FileAccessActions
                                selection={exportContext(
                                  allMatching ? undefined : [...selected],
                                )}
                                folderName={`${folderName}-selected`}
                                scopeSchema={listedName ?? undefined}
                                builderTo={builderHref}
                              />
                              {canExportFiles && (
                                // The files of the records ticked and of everything in
                                // them: the one move dialog.
                                <MoveToDriveButton
                                  label="Move files to drive…"
                                  what={`the files of ${bulkCount.toLocaleString()} record${bulkCount === 1 ? '' : 's'}`}
                                  pick={selectionFor(
                                    x.query,
                                    dataset,
                                    allMatching ? undefined : [...selected],
                                    undefined,
                                    true,
                                  )}
                                  onStarted={picked.clear}
                                />
                              )}
                              {allKinds && (
                                // Edits and workflows are about one kind's fields.
                                <>
                                  <Button
                                    size="sm"
                                    disabled
                                    title={pickKind('run a workflow on them')}
                                  >
                                    Run workflow
                                  </Button>
                                  <Button
                                    size="sm"
                                    disabled
                                    title={pickKind('edit them together')}
                                  >
                                    Edit…
                                  </Button>
                                </>
                              )}
                              {!allMatching && (
                                <BulkRunWorkflow
                                  workflows={runnable}
                                  recordIds={[...selected]}
                                  onStarted={picked.clear}
                                />
                              )}
                              {listed &&
                                bulkEditableFields(listed).length > 0 && (
                                  <Button
                                    size="sm"
                                    disabled={!mayWrite}
                                    title={
                                      mayWrite
                                        ? undefined
                                        : why('write_records')
                                    }
                                    onClick={() => setEditing(true)}
                                  >
                                    Edit…
                                  </Button>
                                )}
                              <Button
                                size="sm"
                                disabled={
                                  !can('change_structure') ||
                                  (allKinds && allMatching)
                                }
                                title={
                                  allKinds && allMatching
                                    ? pickKind('release every matching record')
                                    : can('change_structure')
                                      ? 'Freeze these records, with the files they cite, as a citable release'
                                      : why('change_structure')
                                }
                                onClick={() =>
                                  navigate(
                                    `/releases/new?${new URLSearchParams(
                                      allMatching
                                        ? {
                                            query: JSON.stringify(
                                              queryBody(
                                                { ...x.query, sort: undefined },
                                                dataset,
                                              ),
                                            ),
                                          }
                                        : { records: [...selected].join(',') },
                                    )}`,
                                  )
                                }
                              >
                                Release these…
                              </Button>
                              {(listed || allKinds) && (
                                // Moving takes the records out of this collection, so
                                // it asks for the same permission as deleting here.
                                <Button
                                  size="sm"
                                  disabled={!mayDelete}
                                  title={mayDelete ? undefined : why('delete')}
                                  onClick={() => setMoving(true)}
                                >
                                  Move to…
                                </Button>
                              )}
                            </>
                          }
                        />
                      )}

                      {x.page.error ? (
                        // In place of the rows only: the filters and search stay editable,
                        // since a bad one is usually what caused this.
                        <div className="space-y-2">
                          <ErrorState message={errorMessage(x.page.error)} />
                          {(x.hasSelection || state.q) && (
                            <Button
                              size="sm"
                              onClick={() =>
                                patch({
                                  filter: null,
                                  sort: [],
                                  cols: null,
                                  view: null,
                                  q: '',
                                })
                              }
                            >
                              Reset
                            </Button>
                          )}
                        </div>
                      ) : x.page.isLoading ? (
                        <TableSkeleton
                          columns={['w-8', 'w-24', 'w-32', 'w-32', 'w-24']}
                          rows={8}
                        />
                      ) : rows.length === 0 ? (
                        <EmptyState
                          title={`No ${listedLabel.toLowerCase()} match`}
                          message={
                            state.q || x.filter
                              ? 'Try removing a filter or clearing the search.'
                              : 'Nothing here yet.'
                          }
                        />
                      ) : (
                        <div aria-busy={x.page.isFetching}>
                          <RecordsTable
                            columns={columns}
                            rows={rows}
                            schemas={x.schemas}
                            recordLink={(r) =>
                              openNotesView
                                ? `/records/${r.id}?tab=notes`
                                : `/records/${r.id}`
                            }
                            idHeader={allKinds ? 'Name' : undefined}
                            showAddedColumn={!allKinds}
                            sort={sort}
                            onSortChange={toggleSort}
                            selection={
                              dataset && !inside ? picked.table : undefined
                            }
                            totals={
                              !inside && totalsAsk.length > 0 && totals.data
                                ? {
                                    label: `All ${total.toLocaleString()}`,
                                    cells: totalsCells(
                                      x.columnNames,
                                      totals.data,
                                    ),
                                  }
                                : undefined
                            }
                            trailing={{
                              header: 'Contains',
                              render: (row) => (
                                <DrillLinks
                                  counts={row.child_counts}
                                  byName={x.byName}
                                  onDrill={(child) => drill(row, child)}
                                />
                              ),
                            }}
                          />
                          <Pagination
                            page={state.page}
                            pageSize={state.pageSize}
                            total={total}
                            onPage={(page) => patch({ page })}
                            onPageSize={(pageSize) => patch({ pageSize })}
                          />
                        </div>
                      )}
                    </>
                  )}
                </div>
              }
            />
          </div>
        </div>
      </div>

      {moving && dataset && (listed || allKinds) && (
        <MoveRecordsDialog
          selection={
            allMatching
              ? { query: x.query, collection: dataset }
              : { ids: [...selected] }
          }
          count={bulkCount}
          listed={listed}
          schemas={x.schemas}
          from={dataset}
          onClose={() => setMoving(false)}
          onMoved={picked.clear}
        />
      )}

      {editing && dataset && listed && (
        <BulkEditDialog
          selection={
            allMatching
              ? { query: x.query, collection: dataset }
              : { ids: [...selected] }
          }
          count={bulkCount}
          listed={listed}
          onClose={() => setEditing(false)}
          onDone={picked.clear}
        />
      )}

      {confirmDelete && (
        <ConfirmDialog
          title={`Delete ${pluralise(bulkCount, listedLabel.toLowerCase())}`}
          body={
            allMatching
              ? `Delete all ${total.toLocaleString()} ${listedLabel.toLowerCase()} matching the current filters and search? They move to Recently Deleted — restore any time before they're permanently purged.`
              : `Delete the ${pluralise(selected.size, 'selected record')}? They move to Recently Deleted — restore any time before they're permanently purged.`
          }
          confirmLabel={`Delete ${bulkCount.toLocaleString()}`}
          variant="danger"
          typedConfirmationValue={
            bulkCount > HIGH_IMPACT_RECORD_THRESHOLD
              ? (listed?.name ?? 'delete')
              : undefined
          }
          warning={
            deleteMany.error || deleteMatching.error
              ? errorMessage(deleteMany.error ?? deleteMatching.error)
              : undefined
          }
          isPending={deleteMany.isPending || deleteMatching.isPending}
          onConfirm={confirmBulkDelete}
          onClose={() => setConfirmDelete(false)}
        />
      )}
    </div>
  )
}
