import { useState } from 'react'
import { Link, useParams, useNavigate } from 'react-router-dom'
import { useRecord, useRecords, useUpdateRecord, useCreateRecord, useDeleteRecord } from '../hooks/useRecords'
import { useDataset } from '../hooks/useDatasets'
import { useSchemas } from '../hooks/useSchemas'
import { useWorkflows, useJobs } from '../hooks/useWorkflows'
import type { WorkflowJob } from '../api/workflows'
import { WorkflowRunModal } from '../components/workflows/WorkflowRunModal'
import {
  Badge, Button, MonoId,
  Table, Thead, Th, Tbody, Tr, Td,
  LoadingState, ErrorState,
} from '../components/ui'
import { DynamicField } from '../components/records/DynamicField'
import { RecordForm } from '../components/records/RecordForm'
import { formatDate } from '../lib/utils'
import type { Schema } from '../api/schemas'
import type { CivexRecord } from '../api/records'
import JobsTable from '../components/jobs/JobsTable'

function JobStatusBadge({ status }: { status: WorkflowJob['status'] }) {
  switch (status) {
    case 'completed': return <Badge variant="success">✓ completed</Badge>
    case 'failed':    return <Badge variant="danger">✗ failed</Badge>
    case 'running':   return (
      <span className="inline-flex items-center gap-1 text-xs font-medium text-[#0969da]">
        <span className="animate-spin">↻</span> running
      </span>
    )
    default: return <Badge variant="default">· pending</Badge>
  }
}

function FieldValue({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="text-[#818b98]">—</span>
  if (typeof value === 'boolean') return <Badge variant={value ? 'success' : 'default'}>{String(value)}</Badge>
  if (Array.isArray(value) && value.length > 0 && typeof value[0] === 'object' && 'sha256' in value[0]) {
    const refs = value as { filename: string; size: number; sha256: string }[]
    return (
      <span className="flex flex-col gap-1">
        {refs.map(ref => (
          <span key={ref.sha256} className="inline-flex items-center gap-2 text-xs text-[#656d76]">
            <span>{ref.filename} ({(ref.size / 1024).toFixed(1)} KB)</span>
            <a href={`/api/files/${ref.sha256}?filename=${encodeURIComponent(ref.filename)}`} download={ref.filename} className="text-[#0969da] hover:underline">Download</a>
          </span>
        ))}
      </span>
    )
  }
  if (typeof value === 'object' && 'sha256' in (value as object)) {
    const ref = value as { filename: string; size: number; sha256: string }
    return (
      <span className="inline-flex items-center gap-2 text-xs text-[#656d76]">
        <span>{ref.filename} ({(ref.size / 1024).toFixed(1)} KB)</span>
        <a
          href={`/api/files/${ref.sha256}?filename=${encodeURIComponent(ref.filename)}`}
          download={ref.filename}
          className="text-[#0969da] hover:underline"
        >
          Download
        </a>
      </span>
    )
  }
  return <span>{String(value)}</span>
}

function ChildTable({
  schemaName,
  schema,
  records,
  datasetId,
  onDelete,
}: {
  schemaName: string
  schema: Schema | undefined
  records: CivexRecord[]
  datasetId: string
  onDelete: (id: string) => void
}) {
  const cols = schema?.fields.filter(f => f.type !== 'file').map(f => f.name) ?? []
  const [confirmId, setConfirmId] = useState<string | null>(null)

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold text-[#1f2328] flex items-center gap-2">
        {schema
          ? <Link to={`/schemas/${schema.id}`}><Badge variant="accent">{schemaName}</Badge></Link>
          : <Badge variant="accent">{schemaName}</Badge>
        }
        <span className="font-normal text-[#656d76]">{records.length} record{records.length !== 1 ? 's' : ''}</span>
      </h3>
      <Table>
        <Thead>
          <tr>
            <Th className="w-24">ID</Th>
            {cols.map(c => <Th key={c}>{c}</Th>)}
            <Th className="w-28">Added</Th>
            <Th className="w-20" />
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
              {cols.map(col => (
                <Td key={col}><FieldValue value={r.data[col]} /></Td>
              ))}
              <Td className="text-[#656d76]">{formatDate(r.created_at)}</Td>
              <Td>
                {confirmId === r.id ? (
                  <span className="flex items-center gap-1.5">
                    <button
                      onClick={() => { onDelete(r.id); setConfirmId(null) }}
                      className="text-xs text-[#d1242f] font-medium hover:underline"
                    >
                      Confirm
                    </button>
                    <button
                      onClick={() => setConfirmId(null)}
                      className="text-xs text-[#656d76] hover:underline"
                    >
                      Cancel
                    </button>
                  </span>
                ) : (
                  <button
                    onClick={() => setConfirmId(r.id)}
                    className="text-xs text-[#656d76] hover:text-[#d1242f] transition-colors"
                    title="Delete record"
                  >
                    ✕
                  </button>
                )}
              </Td>
            </Tr>
          ))}
        </Tbody>
      </Table>
    </div>
  )
}

export default function RecordDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [isEditing, setIsEditing] = useState(false)
  const [editValues, setEditValues] = useState<Record<string, unknown>>({})
  const [addingChild, setAddingChild] = useState(false)
  const [runWorkflow, setRunWorkflow] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const { data: record, isLoading, error } = useRecord(id, 3000)
  const { data: dataset } = useDataset(record?.dataset_id ?? '')
  const { data: schemas } = useSchemas()
  const { data: workflows } = useWorkflows()
  const { data: parent } = useRecord(record?.parent_record_id)
  const { data: recordJobs } = useJobs(undefined, id)
  const updateRecord = useUpdateRecord()
  const createRecord = useCreateRecord(dataset?.name ?? '')
  const deleteRecord = useDeleteRecord(dataset?.name ?? '')

  // All children of this record — poll faster while jobs are active
  const hasActiveJobs = (recordJobs ?? []).some(j => j.status === 'pending' || j.status === 'running')
  const { data: childPage } = useRecords(dataset?.name ?? '', {
    parent_record_id: id,
    limit: 500,
  }, hasActiveJobs ? 2000 : 5000)

  if (isLoading) return <LoadingState />
  if (error || !record) return <ErrorState message={error ? String(error) : 'Record not found'} />

  const schema = schemas?.find(s => s.name === record.schema_name)
  const parentSchema = schema?.parent_id ? schemas?.find(s => s.id === schema.parent_id) : null
  const children = childPage?.items ?? []
  const childSchemas = schemas?.filter(s => s.parent_id === schema?.id) ?? []
  const applicableWorkflows = (workflows ?? []).filter(
    wf => !wf.record_schema || wf.record_schema === record.schema_name
  )
  const runWorkflowDef = runWorkflow ? applicableWorkflows.find(wf => wf.name === runWorkflow) ?? null : null

  function startEditing() {
    setEditValues({ ...record!.data })
    setIsEditing(true)
  }

  function saveEditing() {
    const coerced: Record<string, unknown> = {}
    for (const field of schema?.fields ?? []) {
      const v = editValues[field.name]
      if (v === '' || v === undefined || v === null) continue
      if (field.type === 'integer') coerced[field.name] = parseInt(v as string, 10)
      else if (field.type === 'float') coerced[field.name] = parseFloat(v as string)
      else coerced[field.name] = v
    }
    updateRecord.mutate(
      { id: record!.id, data: coerced },
      { onSuccess: () => setIsEditing(false) },
    )
  }

  function handleAddChild(schemaName: string, data: Record<string, unknown>, parentRecordId?: string) {
    createRecord.mutate(
      { schema_name: schemaName, data, parent_record_id: parentRecordId },
      { onSuccess: () => setAddingChild(false) },
    )
  }

  // Group children by schema name for display
  const childrenBySchema = children.reduce<Record<string, CivexRecord[]>>((acc, r) => {
    ;(acc[r.schema_name] ??= []).push(r)
    return acc
  }, {})

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-1.5 text-sm text-[#656d76] flex-wrap">
        <Link to="/datasets" className="hover:text-[#0969da]">Datasets</Link>
        <span>/</span>
        {dataset && (
          <>
            <Link to={`/datasets/${record.dataset_id}`} className="hover:text-[#0969da]">
              {dataset.name}
            </Link>
            <span>/</span>
          </>
        )}
        <span className="font-mono text-[#1f2328]">{record.id.slice(0, 8)}</span>
      </nav>

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-mono font-semibold text-[#1f2328]">{record.id.slice(0, 8)}</h1>
            {schema
              ? <Link to={`/schemas/${schema.id}`}><Badge variant="accent">{record.schema_name}</Badge></Link>
              : <Badge variant="accent">{record.schema_name}</Badge>
            }
          </div>
          <p className="mt-1 text-xs text-[#818b98] font-mono">{record.id}</p>
          <p className="mt-1 text-sm text-[#656d76]">
            Added {formatDate(record.created_at)}
            {record.created_at !== record.updated_at && ` · Updated ${formatDate(record.updated_at)}`}
          </p>
        </div>
      </div>

      {/* Parent record */}
      {record.parent_record_id && (
        <div className="border border-[#d0d7de] rounded-md p-4 bg-[#f6f8fa]">
          <p className="text-xs font-semibold text-[#656d76] uppercase tracking-wide mb-2">
            Parent — {parentSchema?.name ?? 'unknown'}
          </p>
          {parent ? (
            <div className="flex items-center gap-3">
              <Link
                to={`/records/${parent.id}`}
                className="font-mono text-sm text-[#0969da] hover:underline"
              >
                {parent.id.slice(0, 8)}
              </Link>
              <div className="flex gap-3 text-sm text-[#1f2328]">
                {Object.entries(parent.data)
                  .filter(([, v]) => typeof v === 'string' || typeof v === 'number')
                  .slice(0, 3)
                  .map(([k, v]) => (
                    <span key={k}>
                      <span className="text-[#656d76]">{k}:</span> {String(v)}
                    </span>
                  ))}
              </div>
            </div>
          ) : (
            <Link to={`/records/${record.parent_record_id}`} className="font-mono text-sm text-[#0969da] hover:underline">
              {record.parent_record_id.slice(0, 8)}
            </Link>
          )}
        </div>
      )}

      {/* Own fields */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-base font-semibold text-[#1f2328]">Fields</h2>
          {!isEditing && (
            <Button size="sm" onClick={startEditing}>Edit</Button>
          )}
        </div>

        {isEditing ? (
          <div className="border border-[#d0d7de] rounded-md bg-[#f6f8fa] p-4 space-y-4">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {(schema?.fields ?? []).map(field => (
                <div key={field.name} className="flex flex-col gap-1">
                  <label className="text-xs font-medium text-[#1f2328] flex items-center gap-1.5">
                    <span className="font-mono">{field.name}</span>
                    <Badge variant="accent">{field.type}</Badge>
                    {field.required && <Badge variant="success">required</Badge>}
                  </label>
                  <DynamicField
                    field={field}
                    value={editValues[field.name] ?? record.data[field.name]}
                    onChange={v => setEditValues(prev => ({ ...prev, [field.name]: v }))}
                  />
                </div>
              ))}
            </div>
            {updateRecord.error && (
              <p className="text-xs text-[#d1242f]">{String(updateRecord.error)}</p>
            )}
            <div className="flex gap-2">
              <Button variant="primary" size="sm" onClick={saveEditing} disabled={updateRecord.isPending}>
                {updateRecord.isPending ? 'Saving…' : 'Save'}
              </Button>
              <Button size="sm" onClick={() => setIsEditing(false)}>Cancel</Button>
            </div>
          </div>
        ) : Object.keys(record.data).length === 0 ? (
          <p className="text-sm text-[#656d76] italic">No field values.</p>
        ) : (
          <div className="grid grid-cols-1 gap-px bg-[#d0d7de] border border-[#d0d7de] rounded-md overflow-hidden sm:grid-cols-2">
            {(schema?.fields ?? Object.keys(record.data).map(name => ({ name, type: 'string', required: false, id: name }))).map(field => (
              <div key={field.name} className="bg-white px-4 py-3">
                <p className="text-xs text-[#656d76] font-mono mb-0.5 flex items-center gap-1.5">
                  {field.name}
                  {'type' in field && <Badge variant="accent">{(field as { type: string }).type}</Badge>}
                </p>
                <div className="text-sm text-[#1f2328]">
                  <FieldValue value={record.data[field.name]} />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Children */}
      {(childSchemas.length > 0 || Object.keys(childrenBySchema).length > 0) && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-[#1f2328]">
              Children
              <span className="ml-2 text-sm font-normal text-[#656d76]">{children.length} total</span>
            </h2>
            {childSchemas.length > 0 && !addingChild && (
              <Button variant="primary" size="sm" onClick={() => setAddingChild(true)}>
                + Add record
              </Button>
            )}
          </div>

          {addingChild && dataset && schemas && (
            <RecordForm
              schemas={schemas}
              datasetName={dataset.name}
              selectableSchemaIds={childSchemas.map(s => s.id)}
              lockedParentRecordId={record.id}
              onSubmit={handleAddChild}
              onCancel={() => setAddingChild(false)}
              isPending={createRecord.isPending}
              error={createRecord.error ? String(createRecord.error) : null}
            />
          )}

          {Object.entries(childrenBySchema).map(([schemaName, recs]) => (
            <ChildTable
              key={schemaName}
              schemaName={schemaName}
              schema={schemas?.find(s => s.name === schemaName)}
              records={recs}
              datasetId={record.dataset_id}
              onDelete={childId => deleteRecord.mutate(childId)}
            />
          ))}
        </div>
      )}

      {applicableWorkflows.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-base font-semibold text-[#1f2328]">Workflows</h2>
          </div>
          <div className="flex flex-wrap gap-2">
            {applicableWorkflows.map(wf => (
              <button
                key={wf.name}
                onClick={() => setRunWorkflow(wf.name)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-[#d0d7de] rounded-md hover:bg-[#f6f8fa] hover:border-[#0969da] transition-colors text-[#1f2328]"
              >
                <span>▶</span>
                <span className="font-mono text-xs">{wf.name}</span>
                {wf.inputs && Object.values(wf.inputs).some(i => i.type === 'files') && (
                  <span className="text-xs text-[#656d76]">· files</span>
                )}
              </button>
            ))}
          </div>
        </div>
      )}

      {runWorkflowDef && (
        <WorkflowRunModal
          workflow={runWorkflowDef}
          recordId={record.id}
          onClose={() => setRunWorkflow(null)}
        />
      )}

      <JobsTable recordId={record.id} />

      {/* Danger zone */}
      <div className="border border-[#d1242f33] rounded-md">
        <div className="px-4 py-3 border-b border-[#d1242f33] bg-[#ffebe9] rounded-t-md">
          <h2 className="text-sm font-semibold text-[#d1242f]">Danger zone</h2>
        </div>
        <div className="px-4 py-3 flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-[#1f2328]">Delete this record</p>
            <p className="text-xs text-[#656d76]">Permanently removes this record and all its children.</p>
          </div>
          {confirmDelete ? (
            <div className="flex items-center gap-2">
              <span className="text-xs text-[#656d76]">Are you sure?</span>
              <Button
                variant="danger" size="sm"
                onClick={() => deleteRecord.mutate(record.id, {
                  onSuccess: () => navigate(dataset ? `/datasets/${record.dataset_id}` : '/datasets'),
                })}
                disabled={deleteRecord.isPending}
              >
                {deleteRecord.isPending ? 'Deleting…' : 'Confirm delete'}
              </Button>
              <Button size="sm" onClick={() => setConfirmDelete(false)}>Cancel</Button>
            </div>
          ) : (
            <Button variant="danger" size="sm" onClick={() => setConfirmDelete(true)}>
              Delete record
            </Button>
          )}
        </div>
      </div>

    </div>
  )
}
