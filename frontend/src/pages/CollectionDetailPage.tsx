import { useState, useEffect } from 'react'
import { useParams, Link, useNavigate } from 'react-router'
import { Upload, Table as TableIcon } from '../components/ui/icons'
import {
  useCollection,
  useUpdateCollection,
  useDeleteCollection,
} from '../hooks/useCollections'
import {
  useRecords,
  useRecordCounts,
  useCreateRecord,
  useDeleteManyRecords,
  useDeleteAllRecords,
} from '../hooks/useRecords'
import { useSchemas } from '../hooks/useSchemas'
import {
  Button,
  Page,
  DetailSkeleton,
  TableSkeleton,
  ErrorState,
  Field,
  Input,
  TimeZoneSelect,
  Pagination,
  ConfirmDialog,
} from '../components/ui'
import { RecordForm } from '../components/records/RecordForm'
import { CollectionTimeZone } from '../components/records/CollectionTimeZone'
import { RecordsTable } from '../components/records/RecordsTable'
import { AuditTrail } from '../components/audit/AuditTrail'
import { collectionsApi } from '../api/collections'
import { describeAuditEntry as describeCollectionAuditEntry } from '../utils/collectionAudit'
import { errorMessage } from '../lib/errors'
import { HIGH_IMPACT_RECORD_THRESHOLD } from '../lib/deleteImpact'
import type { Schema } from '../api/schemas'
import { displayLabel } from '../utils/naming'

/** Header text comes from the label, the data lookup from the name. */
function schemaColumns(
  schema: Schema,
): { name: string; label: string; type: string }[] {
  return schema.fields
    .filter((f) => f.type !== 'file')
    .map((f) => ({
      name: f.name,
      label: displayLabel(f.name, f.label),
      type: f.type,
    }))
}

export default function CollectionDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [selectedSchema, setSelectedSchema] = useState<string | null>(null)
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(50)
  const [addingRecord, setAddingRecord] = useState(false)
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [editing, setEditing] = useState(false)
  const [timezoneValue, setTimezoneValue] = useState('')
  const [nameValue, setNameValue] = useState('')
  const [descriptionValue, setDescriptionValue] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [confirmDeleteAll, setConfirmDeleteAll] = useState(false)

  useEffect(() => {
    const t = setTimeout(() => {
      setSearch(searchInput)
      setPage(0)
    }, 300)
    return () => clearTimeout(t)
  }, [searchInput])

  const {
    data: collection,
    isLoading: collectionLoading,
    error: collectionError,
  } = useCollection(id!)
  const { data: schemas } = useSchemas()

  // Schema breakdown via a single GROUP BY — no record loading
  const { data: counts } = useRecordCounts(collection?.name ?? '')

  // Paginated records — only what's needed for the current page
  const {
    data: recordsPage,
    isLoading: recordsLoading,
    isFetching: recordsFetching,
    error: recordsError,
  } = useRecords(collection?.name ?? '', {
    schema: selectedSchema ?? undefined,
    search: search || undefined,
    limit: pageSize,
    offset: page * pageSize,
  })

  const createRecord = useCreateRecord(collection?.name ?? '')
  const updateCollection = useUpdateCollection()
  const deleteCollection = useDeleteCollection()
  const deleteManyRecords = useDeleteManyRecords(collection?.name ?? '')
  const deleteAllRecords = useDeleteAllRecords(collection?.name ?? '')

  const breadcrumbs = [{ label: 'Collections', to: '/collections' }]

  if (collectionLoading)
    return (
      <Page
        breadcrumbs={breadcrumbs}
        loading={
          <>
            <DetailSkeleton metadataRows={0} sections={0} />
            <TableSkeleton
              columns={['w-8', 'w-20', 'w-32', 'w-32', 'w-24']}
              rows={8}
            />
          </>
        }
      />
    )
  if (collectionError || !collection)
    return (
      <Page
        breadcrumbs={breadcrumbs}
        error={
          <ErrorState
            message={
              collectionError
                ? errorMessage(collectionError)
                : 'Collection not found'
            }
          />
        }
      />
    )

  const total = recordsPage?.total ?? 0
  const records = recordsPage?.items ?? []

  const activeSchema = schemas?.find((s) => s.name === selectedSchema) ?? null
  const columns = activeSchema ? schemaColumns(activeSchema) : []

  function selectSchema(name: string | null) {
    setSelectedSchema(name)
    setPage(0)
    setSelected(new Set())
  }

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  function toggleSelectAll() {
    if (selected.size === records.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(records.map((r) => r.id)))
    }
  }

  function handleDeleteSelected() {
    deleteManyRecords.mutate([...selected], {
      onSuccess: () => setSelected(new Set()),
    })
  }

  function handleDeleteAll() {
    deleteAllRecords.mutate(selectedSchema ?? undefined, {
      onSuccess: () => setConfirmDeleteAll(false),
    })
  }

  function handleSaveEdit() {
    const newName = nameValue.trim()
    const body: { rename?: string; description?: string; timezone?: string } =
      {}
    if (newName && newName !== collection!.name) body.rename = newName
    if (descriptionValue !== (collection!.description ?? ''))
      body.description = descriptionValue
    // '' clears the zone; omitting leaves it untouched.
    if (timezoneValue !== (collection!.timezone ?? ''))
      body.timezone = timezoneValue
    if (!Object.keys(body).length) {
      setEditing(false)
      return
    }
    updateCollection.mutate(
      { name: collection!.name, body },
      { onSuccess: () => setEditing(false) },
    )
  }

  function handleAddRecord(
    schemaName: string,
    data: Record<string, unknown>,
    parentRecordId?: string,
  ) {
    createRecord.mutate(
      { schema_name: schemaName, data, parent_record_id: parentRecordId },
      { onSuccess: () => setAddingRecord(false) },
    )
  }

  function exportCsv() {
    if (!collection) return
    const qs = new URLSearchParams()
    if (selectedSchema) qs.set('schema', selectedSchema)
    if (search) qs.set('search', search)
    const query = qs.toString() ? `?${qs}` : ''
    window.open(
      `/api/collections/${encodeURIComponent(collection.name)}/export.csv${query}`,
      '_blank',
    )
  }

  return (
    <CollectionTimeZone timeZone={collection.timezone}>
      <Page
        breadcrumbs={[...breadcrumbs, { label: collection.name }]}
        title={collection.name}
        description={collection.description ?? undefined}
        action={
          !editing && (
            <div className="flex items-center gap-2">
              <Link to={`/collections/${id}/import`}>
                <Button size="sm" variant="primary">
                  <Upload size={14} /> Guided import
                </Button>
              </Link>
              <Button
                size="sm"
                variant="default"
                onClick={exportCsv}
                title="Download all records as CSV"
              >
                Export CSV
              </Button>
              <Button
                size="sm"
                onClick={() => {
                  setNameValue(collection.name)
                  setDescriptionValue(collection.description ?? '')
                  setTimezoneValue(collection.timezone ?? '')
                  setEditing(true)
                }}
              >
                Edit
              </Button>
            </div>
          )
        }
      >
        {editing && (
          <div className="border border-border rounded-md p-4 bg-canvas-subtle flex flex-col gap-3">
            <Field label="Collection name">
              <Input
                autoFocus
                value={nameValue}
                onChange={(e) => setNameValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleSaveEdit()
                  if (e.key === 'Escape') setEditing(false)
                }}
              />
            </Field>
            <Field label="Description">
              <Input
                value={descriptionValue}
                onChange={(e) => setDescriptionValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Escape') setEditing(false)
                }}
                placeholder="No description"
              />
            </Field>
            <Field
              label="Timezone"
              hint="Datetimes without a UTC offset are read in this zone, and everyone sees them in it. Existing values are not changed, only how they are shown."
            >
              <TimeZoneSelect
                value={timezoneValue}
                onChange={setTimezoneValue}
                unsetLabel="Not set — each viewer's own timezone"
              />
            </Field>
            {updateCollection.error && (
              <span role="alert" className="text-xs text-danger">
                {errorMessage(updateCollection.error)}
              </span>
            )}
            <div className="flex gap-2">
              <Button
                variant="primary"
                size="sm"
                onClick={handleSaveEdit}
                disabled={updateCollection.isPending || !nameValue.trim()}
              >
                {updateCollection.isPending ? 'Saving…' : 'Save'}
              </Button>
              <Button size="sm" onClick={() => setEditing(false)}>
                Cancel
              </Button>
            </div>
          </div>
        )}

        {/* Schema filter pills + Add button */}
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-2 flex-wrap">
            <button
              onClick={() => selectSchema(null)}
              className={`px-3 py-2 rounded-full text-sm border transition-colors cursor-pointer ${
                selectedSchema === null
                  ? 'bg-fg text-fg-on-emphasis border-fg'
                  : 'bg-canvas text-fg-muted border-border hover:border-fg hover:text-fg'
              }`}
            >
              All{' '}
              <span className="ml-1 text-xs opacity-70">
                {collection.record_count}
              </span>
            </button>

            {counts &&
              Object.entries(counts)
                .sort()
                .map(([name, count]) => (
                  <button
                    key={name}
                    onClick={() => selectSchema(name)}
                    className={`px-3 py-2 rounded-full text-sm border transition-colors cursor-pointer ${
                      selectedSchema === name
                        ? 'bg-fg text-fg-on-emphasis border-fg'
                        : 'bg-canvas text-fg-muted border-border hover:border-fg hover:text-fg'
                    }`}
                  >
                    {name}{' '}
                    <span className="ml-1 text-xs opacity-70">{count}</span>
                  </button>
                ))}
          </div>

          <div className="flex items-center gap-2 flex-shrink-0">
            {activeSchema && (
              <Link to={`/schemas/${activeSchema.id}/views`}>
                <Button
                  size="sm"
                  title={`Saved views for ${displayLabel(activeSchema.name, activeSchema.label)}`}
                >
                  <TableIcon size={14} /> Views
                </Button>
              </Link>
            )}
            {selectedSchema && (
              <Button
                variant="danger"
                size="sm"
                onClick={() => setConfirmDeleteAll(true)}
              >
                Delete all {selectedSchema}
              </Button>
            )}
            {!addingRecord && (
              <Button
                variant="primary"
                size="sm"
                onClick={() => setAddingRecord(true)}
              >
                + Add record
              </Button>
            )}
          </div>
        </div>

        {/* Search */}
        <Field label="Search records" hideLabel>
          <Input
            type="search"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search records…"
            className="w-full"
          />
        </Field>

        {/* Add record form */}
        {addingRecord && schemas && (
          <RecordForm
            schemas={schemas}
            datasetName={collection.name}
            onSubmit={handleAddRecord}
            onCancel={() => setAddingRecord(false)}
            isPending={createRecord.isPending}
            error={createRecord.error}
          />
        )}

        {/* Records table */}
        {recordsLoading ? (
          <TableSkeleton
            columns={['w-8', 'w-20', 'w-32', 'w-32', 'w-32', 'w-24']}
            rows={8}
          />
        ) : recordsError ? (
          <ErrorState message={errorMessage(recordsError)} />
        ) : records.length === 0 ? (
          <div
            role="status"
            aria-live="polite"
            className="flex flex-col items-center justify-center py-16 text-center"
          >
            <svg
              width="40"
              height="40"
              viewBox="0 0 16 16"
              fill="none"
              className="mb-4 text-border"
              aria-hidden
            >
              <rect
                x="1"
                y="2"
                width="14"
                height="12"
                rx="2"
                stroke="currentColor"
                strokeWidth="1.5"
              />
              <path
                d="M4 6h8M4 8.5h5"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
            </svg>
            <h2 className="text-lg font-semibold text-fg mb-2">
              {selectedSchema ? `No ${selectedSchema} records` : 'No records'}
            </h2>
            <p className="text-sm text-fg-muted mb-6 max-w-sm">
              {!selectedSchema ? (
                <>
                  Add your first record using the button above, or use{' '}
                  <Link
                    to={`/collections/${id}/import`}
                    className="text-accent hover:underline"
                  >
                    guided import
                  </Link>{' '}
                  to bring in a folder of files or a spreadsheet.
                </>
              ) : (
                `No ${selectedSchema} records in this collection yet.`
              )}
            </p>
          </div>
        ) : (
          <div aria-busy={recordsFetching}>
            {selected.size > 0 && (
              <div className="flex items-center gap-3 px-3 py-2 bg-accent-subtle border border-accent-muted rounded-md text-sm">
                <span className="text-accent font-medium">
                  {selected.size} selected
                </span>
                <Button
                  variant="danger"
                  size="sm"
                  disabled={deleteManyRecords.isPending}
                  onClick={handleDeleteSelected}
                >
                  {deleteManyRecords.isPending
                    ? 'Deleting…'
                    : `Delete ${selected.size}`}
                </Button>
                <button
                  className="text-xs text-fg-muted hover:text-fg"
                  onClick={() => setSelected(new Set())}
                >
                  Clear selection
                </button>
              </div>
            )}
            <RecordsTable
              columns={columns}
              rows={records}
              schemas={schemas}
              showSchemaColumn={!selectedSchema}
              recordLink={(r) => `/records/${r.id}`}
              selection={{
                selected,
                onToggle: toggleSelect,
                onToggleAll: toggleSelectAll,
              }}
            />

            <Pagination
              page={page}
              pageSize={pageSize}
              total={total}
              onPage={setPage}
              onPageSize={setPageSize}
            />
          </div>
        )}
        <AuditTrail
          queryKey={['collections', collection.name, 'audit']}
          fetchPage={(offset, limit) =>
            collectionsApi.getAudit(collection.name, offset, limit)
          }
          describeEntry={describeCollectionAuditEntry}
          emptyMessage="Changes to this collection will appear here."
        />

        {/* Danger zone */}
        <div className="border border-danger-muted rounded-md">
          <div className="px-4 py-3 border-b border-danger-muted bg-danger-subtle rounded-t-md">
            <h2 className="text-sm font-semibold text-danger">Danger zone</h2>
          </div>
          <div className="px-4 py-3 flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-fg">
                Delete this collection
              </p>
              <p className="text-xs text-fg-muted">
                Moves this collection (and all its records) to Recently Deleted
                — restore it any time before it's permanently purged.
              </p>
            </div>
            <Button
              variant="danger"
              size="sm"
              onClick={() => setConfirmDelete(true)}
            >
              Delete collection
            </Button>
          </div>
        </div>

        {confirmDeleteAll && selectedSchema && (
          <ConfirmDialog
            title={`Delete all ${selectedSchema} records`}
            body={`Delete all ${(counts?.[selectedSchema] ?? 0).toLocaleString()} "${selectedSchema}" record(s) in this collection? They'll move to Recently Deleted — restore any time before they're permanently purged.`}
            confirmLabel={`Delete ${(counts?.[selectedSchema] ?? 0).toLocaleString()} record${(counts?.[selectedSchema] ?? 0) === 1 ? '' : 's'}`}
            variant="danger"
            typedConfirmationValue={
              (counts?.[selectedSchema] ?? 0) > HIGH_IMPACT_RECORD_THRESHOLD
                ? selectedSchema
                : undefined
            }
            warning={
              deleteAllRecords.error
                ? errorMessage(deleteAllRecords.error)
                : undefined
            }
            isPending={deleteAllRecords.isPending}
            onConfirm={handleDeleteAll}
            onClose={() => setConfirmDeleteAll(false)}
          />
        )}

        {confirmDelete && (
          <ConfirmDialog
            title="Delete collection"
            body={
              collection.record_count > 0
                ? `Delete "${collection.name}"? This moves it and its ${collection.record_count.toLocaleString()} record(s) to Recently Deleted — restore any time before it's permanently purged.`
                : `Delete "${collection.name}"? It has no records. It moves to Recently Deleted — restore any time before it's permanently purged.`
            }
            confirmLabel={
              collection.record_count > 0
                ? `Delete collection and ${collection.record_count.toLocaleString()} record${collection.record_count === 1 ? '' : 's'}`
                : 'Delete collection'
            }
            variant="danger"
            typedConfirmationValue={
              collection.record_count > HIGH_IMPACT_RECORD_THRESHOLD
                ? collection.name
                : undefined
            }
            warning={
              deleteCollection.error
                ? errorMessage(deleteCollection.error)
                : undefined
            }
            isPending={deleteCollection.isPending}
            onConfirm={() =>
              deleteCollection.mutate(collection.name, {
                onSuccess: () => navigate('/collections'),
              })
            }
            onClose={() => setConfirmDelete(false)}
          />
        )}
      </Page>
    </CollectionTimeZone>
  )
}
