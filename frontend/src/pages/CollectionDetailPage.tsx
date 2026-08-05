import { useState, useEffect } from 'react'
import { useParams, Link, useNavigate } from 'react-router'
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
  Badge,
  Table,
  Thead,
  Th,
  Tbody,
  Tr,
  Td,
  PageHeader,
  LoadingState,
  ErrorState,
  Input,
  Checkbox,
} from '../components/ui'
import { RecordForm } from '../components/records/RecordForm'
import { formatDate } from '../lib/utils'
import { errorMessage } from '../lib/errors'
import type { Schema } from '../api/schemas'

const PAGE_SIZE = 50

function schemaColumns(schema: Schema): string[] {
  return schema.fields.filter((f) => f.type !== 'file').map((f) => f.name)
}

export default function CollectionDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [selectedSchema, setSelectedSchema] = useState<string | null>(null)
  const [offset, setOffset] = useState(0)
  const [addingRecord, setAddingRecord] = useState(false)
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [renaming, setRenaming] = useState(false)
  const [renameValue, setRenameValue] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [confirmDeleteAll, setConfirmDeleteAll] = useState(false)

  useEffect(() => {
    const t = setTimeout(() => {
      setSearch(searchInput)
      setOffset(0)
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
    data: page,
    isLoading: recordsLoading,
    error: recordsError,
  } = useRecords(collection?.name ?? '', {
    schema: selectedSchema ?? undefined,
    search: search || undefined,
    limit: PAGE_SIZE,
    offset,
  })

  const createRecord = useCreateRecord(collection?.name ?? '')
  const updateCollection = useUpdateCollection()
  const deleteCollection = useDeleteCollection()
  const deleteManyRecords = useDeleteManyRecords(collection?.name ?? '')
  const deleteAllRecords = useDeleteAllRecords(collection?.name ?? '')

  if (collectionLoading) return <LoadingState />
  if (collectionError || !collection)
    return (
      <ErrorState
        message={
          collectionError
            ? errorMessage(collectionError)
            : 'Collection not found'
        }
      />
    )

  const total = page?.total ?? 0
  const records = page?.items ?? []
  const totalPages = Math.ceil(total / PAGE_SIZE)

  const activeSchema = schemas?.find((s) => s.name === selectedSchema) ?? null
  const columns = activeSchema ? schemaColumns(activeSchema) : []

  function selectSchema(name: string | null) {
    setSelectedSchema(name)
    setOffset(0)
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

  function handleRename() {
    const newName = renameValue.trim()
    if (!newName || newName === collection!.name) {
      setRenaming(false)
      return
    }
    updateCollection.mutate(
      { name: collection!.name, body: { rename: newName } },
      { onSuccess: () => setRenaming(false) },
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
    window.open(
      `/api/collections/${encodeURIComponent(collection.name)}/export.csv`,
      '_blank',
    )
  }

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-1.5 text-sm text-fg-muted">
        <Link to="/collections" className="hover:text-accent">
          Collections
        </Link>
        <span>/</span>
        <span className="text-fg font-medium">{collection.name}</span>
      </nav>

      {renaming ? (
        <div className="border border-border rounded-md p-4 bg-canvas-subtle flex items-center gap-3">
          <Input
            autoFocus
            value={renameValue}
            onChange={(e) => setRenameValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleRename()
              if (e.key === 'Escape') setRenaming(false)
            }}
            className="w-64"
          />
          {updateCollection.error && (
            <span className="text-xs text-danger">
              {errorMessage(updateCollection.error)}
            </span>
          )}
          <Button
            variant="primary"
            size="sm"
            onClick={handleRename}
            disabled={updateCollection.isPending || !renameValue.trim()}
          >
            {updateCollection.isPending ? 'Saving…' : 'Save'}
          </Button>
          <Button size="sm" onClick={() => setRenaming(false)}>
            Cancel
          </Button>
        </div>
      ) : (
        <div className="flex items-start justify-between">
          <PageHeader
            title={collection.name}
            description={collection.description ?? undefined}
          />
          <div className="flex items-center gap-2">
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
                setRenameValue(collection.name)
                setRenaming(true)
              }}
            >
              Rename
            </Button>
          </div>
        </div>
      )}

      {/* Schema filter pills + Add button */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => selectSchema(null)}
            className={`px-3 py-1 rounded-full text-sm border transition-colors cursor-pointer ${
              selectedSchema === null
                ? 'bg-fg text-white border-fg'
                : 'bg-white text-fg-muted border-border hover:border-fg hover:text-fg'
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
                  className={`px-3 py-1 rounded-full text-sm border transition-colors cursor-pointer ${
                    selectedSchema === name
                      ? 'bg-fg text-white border-fg'
                      : 'bg-white text-fg-muted border-border hover:border-fg hover:text-fg'
                  }`}
                >
                  {name}{' '}
                  <span className="ml-1 text-xs opacity-70">{count}</span>
                </button>
              ))}
        </div>

        <div className="flex items-center gap-2 flex-shrink-0">
          {selectedSchema &&
            (confirmDeleteAll ? (
              <div className="flex items-center gap-2">
                <span className="text-xs text-fg-muted">
                  Delete all {selectedSchema}?
                </span>
                <Button
                  variant="danger"
                  size="sm"
                  disabled={deleteAllRecords.isPending}
                  onClick={handleDeleteAll}
                >
                  {deleteAllRecords.isPending ? 'Deleting…' : 'Confirm'}
                </Button>
                <Button size="sm" onClick={() => setConfirmDeleteAll(false)}>
                  Cancel
                </Button>
              </div>
            ) : (
              <Button
                variant="danger"
                size="sm"
                onClick={() => setConfirmDeleteAll(true)}
              >
                Delete all {selectedSchema}
              </Button>
            ))}
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
      <Input
        type="search"
        value={searchInput}
        onChange={(e) => setSearchInput(e.target.value)}
        placeholder="Search records…"
        className="w-full"
      />

      {/* Add record form */}
      {addingRecord && schemas && (
        <RecordForm
          schemas={schemas}
          datasetName={collection.name}
          onSubmit={handleAddRecord}
          onCancel={() => setAddingRecord(false)}
          isPending={createRecord.isPending}
          error={createRecord.error ? errorMessage(createRecord.error) : null}
        />
      )}

      {/* Records table */}
      {recordsLoading ? (
        <LoadingState message="Loading records…" />
      ) : recordsError ? (
        <ErrorState message={errorMessage(recordsError)} />
      ) : records.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
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
            {!selectedSchema
              ? 'Add your first record using the button above, or set up a workflow to import data automatically.'
              : `No ${selectedSchema} records in this collection yet.`}
          </p>
        </div>
      ) : (
        <>
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
          <Table>
            <Thead>
              <tr>
                <Th className="w-8">
                  <Checkbox
                    checked={
                      selected.size === records.length && records.length > 0
                    }
                    ref={(el) => {
                      if (el)
                        el.indeterminate =
                          selected.size > 0 && selected.size < records.length
                    }}
                    onChange={toggleSelectAll}
                  />
                </Th>
                <Th className="w-24">ID</Th>
                {!selectedSchema && <Th className="w-32">Schema</Th>}
                {columns.map((col) => (
                  <Th key={col}>{col}</Th>
                ))}
                <Th className="w-32">Added</Th>
              </tr>
            </Thead>
            <Tbody>
              {records.map((r) => (
                <Tr key={r.id}>
                  <Td>
                    <Checkbox
                      checked={selected.has(r.id)}
                      onChange={() => toggleSelect(r.id)}
                    />
                  </Td>
                  <Td>
                    <Link
                      to={`/records/${r.id}`}
                      className="text-xs text-accent hover:underline"
                    >
                      {r.natural_name ?? (
                        <span className="font-mono">{r.id.slice(0, 8)}</span>
                      )}
                    </Link>
                  </Td>
                  {!selectedSchema && (
                    <Td>
                      {(() => {
                        const schemaId = schemas?.find(
                          (s) => s.name === r.schema_name,
                        )?.id
                        return schemaId ? (
                          <Link to={`/schemas/${schemaId}`}>
                            <Badge variant="accent">{r.schema_name}</Badge>
                          </Link>
                        ) : (
                          <Badge variant="accent">{r.schema_name}</Badge>
                        )
                      })()}
                    </Td>
                  )}
                  {columns.map((col) => (
                    <Td key={col} className="text-fg">
                      {r.data[col] !== undefined && r.data[col] !== null ? (
                        String(r.data[col])
                      ) : (
                        <span className="text-fg-subtle">—</span>
                      )}
                    </Td>
                  ))}
                  <Td className="text-fg-muted">{formatDate(r.created_at)}</Td>
                </Tr>
              ))}
            </Tbody>
          </Table>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between text-sm text-fg-muted">
              <span>
                {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
              </span>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  disabled={offset === 0}
                  onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
                >
                  ← Previous
                </Button>
                <Button
                  size="sm"
                  disabled={offset + PAGE_SIZE >= total}
                  onClick={() => setOffset((o) => o + PAGE_SIZE)}
                >
                  Next →
                </Button>
              </div>
            </div>
          )}
        </>
      )}
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
              Permanently removes this collection and all its records.
            </p>
          </div>
          {confirmDelete ? (
            <div className="flex items-center gap-2">
              <span className="text-xs text-fg-muted">Are you sure?</span>
              <Button
                variant="danger"
                size="sm"
                onClick={() =>
                  deleteCollection.mutate(collection.name, {
                    onSuccess: () => navigate('/collections'),
                  })
                }
                disabled={deleteCollection.isPending}
              >
                {deleteCollection.isPending ? 'Deleting…' : 'Confirm delete'}
              </Button>
              <Button size="sm" onClick={() => setConfirmDelete(false)}>
                Cancel
              </Button>
            </div>
          ) : (
            <Button
              variant="danger"
              size="sm"
              onClick={() => setConfirmDelete(true)}
            >
              Delete collection
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}
