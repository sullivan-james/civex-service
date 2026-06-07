import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useDataset } from '../hooks/useDatasets'
import { useRecords, useRecordCounts, useCreateRecord } from '../hooks/useRecords'
import { useSchemas } from '../hooks/useSchemas'
import {
  Button, Badge, MonoId,
  Table, Thead, Th, Tbody, Tr, Td,
  PageHeader, LoadingState, ErrorState, EmptyState,
} from '../components/ui'
import { RecordForm } from '../components/records/RecordForm'
import { formatDate } from '../lib/utils'
import type { Schema } from '../api/schemas'

const PAGE_SIZE = 50

function schemaColumns(schema: Schema): string[] {
  return schema.fields.filter(f => f.type !== 'file').map(f => f.name)
}

export default function DatasetDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [selectedSchema, setSelectedSchema] = useState<string | null>(null)
  const [offset, setOffset] = useState(0)
  const [addingRecord, setAddingRecord] = useState(false)
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')

  useEffect(() => {
    const t = setTimeout(() => { setSearch(searchInput); setOffset(0) }, 300)
    return () => clearTimeout(t)
  }, [searchInput])

  const { data: dataset, isLoading: datasetLoading, error: datasetError } = useDataset(id!)
  const { data: schemas } = useSchemas()

  // Schema breakdown via a single GROUP BY — no record loading
  const { data: counts } = useRecordCounts(dataset?.name ?? '')

  // Paginated records — only what's needed for the current page
  const {
    data: page,
    isLoading: recordsLoading,
    error: recordsError,
  } = useRecords(dataset?.name ?? '', {
    schema: selectedSchema ?? undefined,
    search: search || undefined,
    limit: PAGE_SIZE,
    offset,
  })

  const createRecord = useCreateRecord(dataset?.name ?? '')

  if (datasetLoading) return <LoadingState />
  if (datasetError || !dataset) return <ErrorState message={datasetError ? String(datasetError) : 'Dataset not found'} />

  const total = page?.total ?? 0
  const records = page?.items ?? []
  const totalPages = Math.ceil(total / PAGE_SIZE)
  const currentPage = Math.floor(offset / PAGE_SIZE)

  const activeSchema = schemas?.find(s => s.name === selectedSchema) ?? null
  const columns = activeSchema ? schemaColumns(activeSchema) : []

  function selectSchema(name: string | null) {
    setSelectedSchema(name)
    setOffset(0)
  }

  function handleAddRecord(schemaName: string, data: Record<string, unknown>, parentRecordId?: string) {
    createRecord.mutate(
      { schema_name: schemaName, data, parent_record_id: parentRecordId },
      { onSuccess: () => setAddingRecord(false) },
    )
  }

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-1.5 text-sm text-[#656d76]">
        <Link to="/datasets" className="hover:text-[#0969da]">Datasets</Link>
        <span>/</span>
        <span className="text-[#1f2328] font-medium">{dataset.name}</span>
      </nav>

      <PageHeader title={dataset.name} description={dataset.description ?? undefined} />

      {/* Schema filter pills + Add button */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => selectSchema(null)}
            className={`px-3 py-1 rounded-full text-sm border transition-colors cursor-pointer ${
              selectedSchema === null
                ? 'bg-[#1f2328] text-white border-[#1f2328]'
                : 'bg-white text-[#656d76] border-[#d0d7de] hover:border-[#1f2328] hover:text-[#1f2328]'
            }`}
          >
            All <span className="ml-1 text-xs opacity-70">{dataset.record_count}</span>
          </button>

          {counts && Object.entries(counts).sort().map(([name, count]) => (
            <button
              key={name}
              onClick={() => selectSchema(name)}
              className={`px-3 py-1 rounded-full text-sm border transition-colors cursor-pointer ${
                selectedSchema === name
                  ? 'bg-[#1f2328] text-white border-[#1f2328]'
                  : 'bg-white text-[#656d76] border-[#d0d7de] hover:border-[#1f2328] hover:text-[#1f2328]'
              }`}
            >
              {name} <span className="ml-1 text-xs opacity-70">{count}</span>
            </button>
          ))}
        </div>

        {!addingRecord && (
          <Button variant="primary" size="sm" onClick={() => setAddingRecord(true)}>
            + Add record
          </Button>
        )}
      </div>

      {/* Search */}
      <input
        type="search"
        value={searchInput}
        onChange={e => setSearchInput(e.target.value)}
        placeholder="Search records…"
        className="w-full border border-[#d0d7de] rounded-md px-3 py-1.5 text-sm bg-white focus:outline-none focus:border-[#0969da] focus:ring-1 focus:ring-[#0969da]"
      />

      {/* Add record form */}
      {addingRecord && schemas && (
        <RecordForm
          schemas={schemas}
          datasetName={dataset.name}
          onSubmit={handleAddRecord}
          onCancel={() => setAddingRecord(false)}
          isPending={createRecord.isPending}
          error={createRecord.error ? String(createRecord.error) : null}
        />
      )}

      {/* Records table */}
      {recordsLoading ? (
        <LoadingState message="Loading records…" />
      ) : recordsError ? (
        <ErrorState message={String(recordsError)} />
      ) : records.length === 0 ? (
        <EmptyState
          title={selectedSchema ? `No ${selectedSchema} records` : 'No records yet'}
          message={!selectedSchema ? 'Click "+ Add record" to add the first one.' : undefined}
        />
      ) : (
        <>
          <Table>
            <Thead>
              <tr>
                <Th className="w-24">ID</Th>
                {!selectedSchema && <Th className="w-32">Schema</Th>}
                {columns.map(col => <Th key={col}>{col}</Th>)}
                <Th className="w-32">Added</Th>
              </tr>
            </Thead>
            <Tbody>
              {records.map(r => (
                <Tr key={r.id}>
                  <Td>
                    <Link to={`/records/${r.id}`} className="font-mono text-xs text-[#0969da] hover:underline">
                      {r.id.slice(0, 8)}
                    </Link>
                  </Td>
                  {!selectedSchema && (
                    <Td>
                      {(() => {
                        const schemaId = schemas?.find(s => s.name === r.schema_name)?.id
                        return schemaId
                          ? <Link to={`/schemas/${schemaId}`}><Badge variant="accent">{r.schema_name}</Badge></Link>
                          : <Badge variant="accent">{r.schema_name}</Badge>
                      })()}
                    </Td>
                  )}
                  {columns.map(col => (
                    <Td key={col} className="text-[#1f2328]">
                      {r.data[col] !== undefined && r.data[col] !== null
                        ? String(r.data[col])
                        : <span className="text-[#818b98]">—</span>
                      }
                    </Td>
                  ))}
                  <Td className="text-[#656d76]">{formatDate(r.created_at)}</Td>
                </Tr>
              ))}
            </Tbody>
          </Table>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between text-sm text-[#656d76]">
              <span>
                {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
              </span>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  disabled={offset === 0}
                  onClick={() => setOffset(o => Math.max(0, o - PAGE_SIZE))}
                >
                  ← Previous
                </Button>
                <Button
                  size="sm"
                  disabled={offset + PAGE_SIZE >= total}
                  onClick={() => setOffset(o => o + PAGE_SIZE)}
                >
                  Next →
                </Button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
