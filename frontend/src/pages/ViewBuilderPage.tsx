import { useEffect, useMemo, useState } from 'react'
import { useParams, useNavigate } from 'react-router'
import { useSchema, useSchemas } from '../hooks/useSchemas'
import {
  useView,
  useCreateView,
  useUpdateView,
  useDeleteView,
  useViewPreview,
} from '../hooks/useViews'
import {
  Page,
  Button,
  Input,
  Field,
  Pagination,
  DEFAULT_PAGE_SIZES,
  ConfirmDialog,
  DetailSkeleton,
  TableSkeleton,
  ErrorState,
  EmptyState,
} from '../components/ui'
import {
  RecordsTable,
  type RecordsTableSort,
} from '../components/records/RecordsTable'
import { ColumnPicker, columnLabel } from '../components/views/ColumnPicker'
import { FilterBuilder } from '../components/views/FilterBuilder'
import { collectFields, joinableColumns } from '../utils/viewFields'
import {
  emptyGroup,
  toWireFilterTree,
  wireToRootGroup,
  type FilterGroupNode,
} from '../utils/filterTree'
import type { ViewSortEntry, PreviewViewBody } from '../api/views'
import { displayLabel, nameError } from '../utils/naming'
import { errorMessage } from '../lib/errors'
import { pluralise } from '../lib/utils'

function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(timer)
  }, [value, delayMs])
  return debounced
}

export default function ViewBuilderPage() {
  const { id, viewName } = useParams<{ id: string; viewName?: string }>()
  const isEdit = !!viewName
  const navigate = useNavigate()

  const {
    data: schema,
    isLoading: schemaLoading,
    error: schemaError,
  } = useSchema(id!)
  const { data: allSchemas } = useSchemas()
  const schemaName = schema?.name ?? ''

  const existingView = useView(schemaName, viewName ?? '')

  const [name, setName] = useState('')
  const [columns, setColumns] = useState<string[]>([])
  const [filterRoot, setFilterRoot] = useState<FilterGroupNode>(() =>
    emptyGroup(),
  )
  const [sort, setSort] = useState<RecordsTableSort | undefined>(undefined)
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZES[0])
  const [confirmDelete, setConfirmDelete] = useState(false)

  // Seed builder state from the fetched view exactly once, the first render
  // where it's available -- not a useEffect, so it lands before paint
  // instead of triggering a second commit. Keyed on viewName (via
  // hydrationKey) so switching views (or leaving edit for "new") reseeds.
  const hydrationKey = isEdit ? viewName : 'new'
  const [hydratedFor, setHydratedFor] = useState<string | undefined>(
    isEdit ? undefined : hydrationKey,
  )
  const hydrated = hydratedFor === hydrationKey
  if (!hydrated && isEdit && existingView.data) {
    setHydratedFor(hydrationKey)
    setName(existingView.data.name)
    setColumns(existingView.data.columns)
    setFilterRoot(wireToRootGroup(existingView.data.filter_tree))
    const firstSort = existingView.data.sort[0]
    setSort(
      firstSort
        ? { key: firstSort.field, direction: firstSort.direction }
        : undefined,
    )
  }

  const schemasById = useMemo(
    () => new Map((allSchemas ?? []).map((s) => [s.id, s])),
    [allSchemas],
  )
  const schemasByName = useMemo(
    () => new Map((allSchemas ?? []).map((s) => [s.name, s])),
    [allSchemas],
  )
  const baseFields = useMemo(
    () => (schema ? collectFields(schema, schemasById) : []),
    [schema, schemasById],
  )
  const joinable = useMemo(
    () => (schema ? joinableColumns(schema, schemasById, schemasByName) : []),
    [schema, schemasById, schemasByName],
  )

  const previewSort: ViewSortEntry[] = sort
    ? [{ field: sort.key, direction: sort.direction }]
    : []
  const matchSignature = JSON.stringify({
    columns,
    filter_tree: toWireFilterTree(filterRoot),
    sort: previewSort,
  })
  // A new column/filter/sort selection invalidates whatever page we were
  // on -- reset during render (see the hydration comment above) rather
  // than in an effect.
  const [prevMatchSignature, setPrevMatchSignature] = useState(matchSignature)
  if (matchSignature !== prevMatchSignature) {
    setPrevMatchSignature(matchSignature)
    setPage(0)
  }

  const previewRequest: PreviewViewBody = useMemo(
    () => ({
      columns,
      filter_tree: toWireFilterTree(filterRoot),
      sort: previewSort,
      limit: pageSize,
      offset: page * pageSize,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [columns, filterRoot, sort, page, pageSize],
  )
  const debouncedRequest = useDebouncedValue(previewRequest, 400)
  const preview = useViewPreview(schemaName, debouncedRequest, hydrated)

  const createView = useCreateView(schemaName)
  const updateView = useUpdateView(schemaName, viewName ?? '')
  const deleteView = useDeleteView(schemaName)

  const saveError = isEdit ? updateView.error : createView.error
  const isSaving = isEdit ? updateView.isPending : createView.isPending
  const nameInvalid = nameError(name)

  function handleSave() {
    if (nameInvalid) return
    const body = {
      columns,
      filter_tree: toWireFilterTree(filterRoot),
      sort: previewSort,
    }
    if (isEdit) {
      updateView.mutate(
        { ...body, rename: name !== viewName ? name : undefined },
        {
          onSuccess: (updated) => {
            if (updated.name !== viewName) {
              navigate(`/schemas/${id}/views/${updated.name}`, {
                replace: true,
              })
            }
          },
        },
      )
    } else {
      createView.mutate(
        { name, ...body },
        {
          onSuccess: (created) =>
            navigate(`/schemas/${id}/views/${created.name}`, { replace: true }),
        },
      )
    }
  }

  function handleSortChange(key: string) {
    setSort((current) => {
      if (!current || current.key !== key) return { key, direction: 'asc' }
      if (current.direction === 'asc') return { key, direction: 'desc' }
      return undefined
    })
  }

  const breadcrumbs = [
    { label: 'Schemas', to: '/schemas' },
    ...(schema
      ? [
          {
            label: displayLabel(schema.name, schema.label),
            to: `/schemas/${id}`,
          },
        ]
      : []),
    { label: 'Views', to: `/schemas/${id}/views` },
  ]

  if (schemaLoading || (isEdit && existingView.isLoading && !hydrated)) {
    return (
      <Page
        breadcrumbs={breadcrumbs}
        loading={<DetailSkeleton sections={3} />}
      />
    )
  }
  if (schemaError || !schema) {
    return (
      <Page
        breadcrumbs={breadcrumbs}
        error={
          <ErrorState
            message={
              schemaError ? errorMessage(schemaError) : 'Schema not found'
            }
          />
        }
      />
    )
  }
  if (isEdit && existingView.error) {
    return (
      <Page
        breadcrumbs={breadcrumbs}
        error={<ErrorState message={errorMessage(existingView.error)} />}
      />
    )
  }

  const previewColumns = columns.map((col) => ({
    name: col,
    label: columnLabel(col, baseFields, joinable),
  }))
  // Preview rows carry no record id (they're flattened column projections,
  // not records) -- the row's index gives RecordsTable a stable identity.
  const previewRows = (preview.data?.rows ?? []).map((row, index) => ({
    id: String(index),
    data: row,
  }))

  return (
    <Page
      breadcrumbs={breadcrumbs}
      title={isEdit ? `Edit view "${viewName}"` : 'New view'}
      description={`Against ${displayLabel(schema.name, schema.label)}`}
      action={
        <div className="flex items-center gap-2">
          {isEdit && (
            <Button
              variant="danger"
              size="sm"
              onClick={() => setConfirmDelete(true)}
            >
              Delete view
            </Button>
          )}
          <Button
            variant="primary"
            size="sm"
            onClick={handleSave}
            disabled={!!nameInvalid || isSaving}
          >
            {isSaving ? 'Saving…' : 'Save view'}
          </Button>
        </div>
      }
    >
      <div className="max-w-xs">
        <Field
          label="View name"
          error={name ? nameInvalid : undefined}
          required
        >
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="my_view"
          />
        </Field>
      </div>
      {saveError && (
        <p className="text-xs text-danger">{errorMessage(saveError)}</p>
      )}

      <div>
        <h2 className="text-base font-semibold text-fg mb-2">Columns</h2>
        <ColumnPicker
          columns={columns}
          onChange={setColumns}
          baseFields={baseFields}
          joinable={joinable}
        />
      </div>

      <div>
        <h2 className="text-base font-semibold text-fg mb-2">Filters</h2>
        <FilterBuilder
          root={filterRoot}
          fields={baseFields}
          onChange={setFilterRoot}
        />
      </div>

      <div>
        <h2 className="text-base font-semibold text-fg mb-2">
          Preview
          {preview.data && (
            <span className="ml-2 text-sm font-normal text-fg-muted">
              {pluralise(preview.data.total, 'matching record')}
            </span>
          )}
        </h2>
        {columns.length === 0 ? (
          <p className="text-sm text-fg-subtle italic">
            Pick at least one column above to preview matching records.
          </p>
        ) : preview.isLoading ? (
          <TableSkeleton
            columns={previewColumns.map(() => 'w-32')}
            rows={pageSize}
          />
        ) : preview.error ? (
          <ErrorState message={errorMessage(preview.error)} />
        ) : previewRows.length === 0 ? (
          <EmptyState
            title="No matching records"
            message="No records match the current filters."
          />
        ) : (
          <>
            <RecordsTable
              columns={previewColumns}
              rows={previewRows}
              showIdColumn={false}
              showAddedColumn={false}
              sort={sort}
              onSortChange={handleSortChange}
            />
            <Pagination
              page={page}
              pageSize={pageSize}
              total={preview.data?.total ?? 0}
              onPage={setPage}
              onPageSize={setPageSize}
            />
          </>
        )}
      </div>

      {confirmDelete && (
        <ConfirmDialog
          title="Delete view"
          body={`Delete view '${viewName}'? This cannot be undone.`}
          confirmLabel="Delete"
          variant="danger"
          isPending={deleteView.isPending}
          warning={
            deleteView.error ? errorMessage(deleteView.error) : undefined
          }
          onConfirm={() =>
            deleteView.mutate(viewName!, {
              onSuccess: () => navigate(`/schemas/${id}/views`),
            })
          }
          onClose={() => setConfirmDelete(false)}
        />
      )}
    </Page>
  )
}
