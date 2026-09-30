import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { recordsApi, type CivexRecord } from '../../api/records'
import { viewsApi } from '../../api/views'
import {
  useDeleteManyRecords,
  useDeleteMatchingRecords,
} from '../../hooks/useRecords'
import {
  useCreateView,
  useDeleteView,
  useUpdateView,
} from '../../hooks/useViews'
import {
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorState,
  Input,
  Pagination,
  TriggerPopover,
  TableSkeleton,
  Field,
} from '../ui'
import { Columns3, Download, Plus } from '../ui/icons'
import { toTableRows } from '../records/tableRows'
import {
  RecordsTable,
  type RecordsTableRow,
  type RecordsTableSort,
} from '../records/RecordsTable'
import { ColumnPicker, columnLabel } from '../views/ColumnPicker'
import { FilterControls } from './FilterControls'
import { DrillLinks } from './DrillLinks'
import { SavedViewBar } from './SavedViewBar'
import { ScopeTrail, type TrailItem } from './ScopeTrail'
import { SelectionBar } from './SelectionBar'
import { useExplorer, type ExplorerScope } from './useExplorer'
import { viewPatch } from '../../utils/explorerState'
import { ancestorSchemas } from '../../utils/hierarchy'
import { HIGH_IMPACT_RECORD_THRESHOLD } from '../../lib/deleteImpact'
import { errorMessage } from '../../lib/errors'
import { pluralise } from '../../lib/utils'
import { displayLabel } from '../../utils/naming'

export interface RecordsExplorerProps extends ExplorerScope {
  /** Shown as the first crumb when browsing a whole collection. */
  scopeLabel?: string
  /** Extra buttons on the toolbar (e.g. Import). */
  toolbarActions?: ReactNode
  /** Shown instead of the table when there is nothing in scope at all. */
  emptyHint?: ReactNode
}

/** The one way records are browsed: a collection, a single record's
 * descendants at any depth, or a schema across collections. A hierarchy rail
 * picks the level, a trail shows where you are, search + filters + saved
 * filters narrow it, and every row links down to its children. All state is
 * in the URL. */
export function RecordsExplorer({
  scopeLabel,
  toolbarActions,
  emptyHint,
  ...scope
}: RecordsExplorerProps) {
  const x = useExplorer(scope)
  const { state, patch, listed, listedName } = x
  const dataset = scope.dataset

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

  // --- `?view=name` in a shared link: apply it once, when nothing else was
  // chosen. Only ever on arrival -- afterwards the URL is the truth, so
  // clearing the filter of a view stays cleared.
  const seededView = useRef(false)
  useEffect(() => {
    if (seededView.current || !x.viewsLoaded) return
    seededView.current = true
    if (x.activeView && !x.hasSelection) patch(viewPatch(x.activeView))
  }, [x.viewsLoaded, x.activeView, x.hasSelection, patch])

  // --- selection (only where rows can be deleted)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [allMatching, setAllMatching] = useState(false)
  const selectionKey = JSON.stringify([
    listedName,
    x.rootId,
    x.query,
    state.page,
    state.pageSize,
  ])
  const [seenKey, setSeenKey] = useState(selectionKey)
  if (selectionKey !== seenKey) {
    setSeenKey(selectionKey)
    setSelected(new Set())
    setAllMatching(false)
  }
  const [confirmDelete, setConfirmDelete] = useState(false)
  const deleteMany = useDeleteManyRecords(dataset ?? '')
  const deleteMatching = useDeleteMatchingRecords(dataset ?? '')
  const createView = useCreateView(listedName ?? '')
  const updateView = useUpdateView(listedName ?? '', x.activeView?.name ?? '')
  const deleteView = useDeleteView(listedName ?? '')

  const items = x.page.data?.items ?? []
  const total = x.page.data?.total ?? 0
  const rows = toTableRows(items)
  const columns = x.columnNames.map((name) => ({
    name,
    label: columnLabel(name, x.baseFields, x.joinable),
    type: x.baseFields.find((f) => f.name === name)?.type,
    sortable: !name.includes('.'),
  }))
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

  const exportHref =
    dataset && listedName
      ? recordsApi.exportCsvUrl(dataset, { ...x.query, sort: x.sort })
      : x.activeView && !x.modified && listedName
        ? viewsApi.exportUrl(listedName, x.activeView.name, 'csv')
        : null

  const parentIsRoot =
    listed && x.scopeSchema && listed.parent_id === x.scopeSchema.id
  // A new record of the listed schema, under the record being browsed when
  // that is its parent.
  const newRecordHref = `/collections/${dataset}/new?${new URLSearchParams({
    ...(listed ? { schema: listed.name } : {}),
    ...(parentIsRoot && x.rootId ? { parent: x.rootId } : {}),
  })}`
  const bulkCount = allMatching ? total : selected.size
  const listedLabel = listed ? displayLabel(listed.name, listed.label) : ''

  function confirmBulkDelete() {
    const done = {
      onSuccess: () => {
        setSelected(new Set())
        setAllMatching(false)
        setConfirmDelete(false)
      },
    }
    if (allMatching) deleteMatching.mutate(x.query, done)
    else deleteMany.mutate([...selected], done)
  }

  if (!listed && !x.page.isLoading && x.levels.length === 0)
    return (
      <EmptyState
        title="No records yet"
        message={emptyHint ?? 'Add a record to get started.'}
      />
    )

  return (
    <div>
      <div className="min-w-0 space-y-3">
        <ScopeTrail items={trail} heading={listedLabel} />

        <div className="flex flex-wrap items-center gap-2">
          <div className="min-w-[14rem] max-w-xl flex-1">
            <Field label="Search records" hideLabel>
              <Input
                type="search"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder={`Search ${listedLabel.toLowerCase() || 'records'}…`}
                className="w-full"
              />
            </Field>
          </div>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            {toolbarActions}
            <TriggerPopover
              label="Choose columns"
              align="right"
              panelClassName="w-[36rem] max-w-[90vw]"
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
              />
              {x.cols && (
                <button
                  type="button"
                  onClick={() => patch({ cols: null })}
                  className="mt-2 text-xs text-fg-muted underline cursor-pointer"
                >
                  Reset to default columns
                </button>
              )}
            </TriggerPopover>
            {exportHref ? (
              <a href={exportHref} download>
                <Button
                  size="sm"
                  title="Downloads exactly the rows listed below"
                >
                  <Download size={14} /> Export
                </Button>
              </a>
            ) : (
              <Button size="sm" disabled title="Save as a view to export">
                <Download size={14} /> Export
              </Button>
            )}
            {dataset && listed && (
              <Link to={newRecordHref}>
                <Button variant="primary" size="sm">
                  <Plus size={14} /> Add {listedLabel.toLowerCase()}
                </Button>
              </Link>
            )}
          </div>
        </div>

        <SavedViewBar
          views={x.views}
          activeView={x.activeView}
          modified={x.modified}
          hasSelection={x.hasSelection}
          onApply={(v) => patch(viewPatch(v))}
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
          pending={
            createView.isPending || updateView.isPending || deleteView.isPending
          }
          error={createView.error ?? updateView.error ?? deleteView.error}
        />

        {listed && (
          <FilterControls
            wire={x.filter}
            fields={x.filterFields}
            listedSchema={listed.name}
            onChange={(filter) => patch({ filter })}
          />
        )}
        {x.ignoredConditions > 0 && (
          <p className="text-xs text-fg-muted">
            {pluralise(x.ignoredConditions, 'filter')} on another branch of the
            hierarchy {x.ignoredConditions === 1 ? "doesn't" : "don't"} apply
            here.
          </p>
        )}

        {!x.page.error && (
          <p className="text-sm text-fg-muted" aria-live="polite">
            <span className="font-medium text-fg">
              {total.toLocaleString()}
            </span>{' '}
            {listedLabel.toLowerCase()}
            {state.q && <> matching “{state.q}”</>}
          </p>
        )}

        {dataset && (
          <SelectionBar
            selectedCount={selected.size}
            pageCount={rows.length}
            total={total}
            allMatching={allMatching}
            onSelectAllMatching={() => setAllMatching(true)}
            onClear={() => {
              setSelected(new Set())
              setAllMatching(false)
            }}
            onDelete={() => setConfirmDelete(true)}
            deleting={deleteMany.isPending || deleteMatching.isPending}
          />
        )}

        {x.page.error ? (
          // In place of the rows only: the filters and search stay editable,
          // since a bad one is usually what caused this.
          <div className="space-y-2">
            <ErrorState message={errorMessage(x.page.error)} />
            {(x.hasSelection || state.q) && (
              <p className="text-sm text-fg-muted">
                Change or remove the filters above, or{' '}
                <button
                  type="button"
                  className="text-accent hover:underline cursor-pointer"
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
                  clear them all
                </button>
                .
              </p>
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
              recordLink={(r) => `/records/${r.id}`}
              sort={sort}
              onSortChange={toggleSort}
              selection={
                dataset
                  ? {
                      selected: allMatching
                        ? new Set(rows.map((r) => r.id))
                        : selected,
                      onToggle: (id) => {
                        setAllMatching(false)
                        setSelected((prev) => {
                          const next = new Set(prev)
                          if (!next.delete(id)) next.add(id)
                          return next
                        })
                      },
                      onToggleAll: () => {
                        setAllMatching(false)
                        setSelected(
                          selected.size === rows.length
                            ? new Set()
                            : new Set(rows.map((r) => r.id)),
                        )
                      },
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
        {listed && listed.parent_id && !scope.root && x.chain.length === 0 && (
          <p className="text-xs text-fg-muted">
            Listing every {listedLabel.toLowerCase()} in this collection —{' '}
            <Link
              className="text-accent hover:underline"
              to={`/schemas/${listed.parent_id}`}
            >
              open its parent schema
            </Link>{' '}
            to start from the top of the hierarchy.
          </p>
        )}
      </div>

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
            bulkCount > HIGH_IMPACT_RECORD_THRESHOLD ? listed?.name : undefined
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
