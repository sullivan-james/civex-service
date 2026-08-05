import { useState } from 'react'
import { Link, useParams, useNavigate } from 'react-router'
import {
  useRecord,
  useRecords,
  useUpdateRecord,
  useCreateRecord,
  useDeleteRecord,
} from '../hooks/useRecords'
import { useCollection } from '../hooks/useCollections'
import { useSchemas } from '../hooks/useSchemas'
import { useWorkflows, useJobs } from '../hooks/useWorkflows'
import { WorkflowRunModal } from '../components/workflows/WorkflowRunModal'
import {
  Badge,
  Button,
  Table,
  Thead,
  Th,
  Tbody,
  Tr,
  Td,
  LoadingState,
  ErrorState,
} from '../components/ui'
import { DynamicField } from '../components/records/DynamicField'
import { RecordForm } from '../components/records/RecordForm'
import { formatDate } from '../lib/utils'
import { errorMessage } from '../lib/errors'
import type { Schema } from '../api/schemas'
import type { CivexRecord } from '../api/records'
import JobsTable from '../components/jobs/JobsTable'

function FieldValue({ value }: { value: unknown }) {
  if (value === null || value === undefined)
    return <span className="text-fg-subtle">—</span>
  if (typeof value === 'boolean')
    return (
      <Badge variant={value ? 'success' : 'default'}>{String(value)}</Badge>
    )
  if (
    Array.isArray(value) &&
    value.length > 0 &&
    typeof value[0] === 'object' &&
    'sha256' in value[0]
  ) {
    const refs = value as { filename: string; size: number; sha256: string }[]
    return (
      <span className="flex flex-col gap-1">
        {refs.map((ref) => (
          <span
            key={ref.sha256}
            className="inline-flex items-center gap-2 text-sm text-fg-muted"
          >
            <span>
              {ref.filename} ({(ref.size / 1024).toFixed(1)} KB)
            </span>
            <a
              href={`/api/files/${ref.sha256}?filename=${encodeURIComponent(ref.filename)}`}
              download={ref.filename}
              className="text-accent hover:underline"
            >
              Download
            </a>
          </span>
        ))}
      </span>
    )
  }
  if (typeof value === 'object' && 'sha256' in (value as object)) {
    const ref = value as { filename: string; size: number; sha256: string }
    return (
      <span className="inline-flex items-center gap-2 text-sm text-fg-muted">
        <span>
          {ref.filename} ({(ref.size / 1024).toFixed(1)} KB)
        </span>
        <a
          href={`/api/files/${ref.sha256}?filename=${encodeURIComponent(ref.filename)}`}
          download={ref.filename}
          className="text-accent hover:underline"
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
  onDelete,
}: {
  schemaName: string
  schema: Schema | undefined
  records: CivexRecord[]
  onDelete: (id: string) => void
}) {
  const cols =
    schema?.fields.filter((f) => f.type !== 'file').map((f) => f.name) ?? []
  const [confirmId, setConfirmId] = useState<string | null>(null)

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold text-fg flex items-center gap-2">
        {schema ? (
          <Link to={`/schemas/${schema.id}`}>
            <Badge variant="accent">{schemaName}</Badge>
          </Link>
        ) : (
          <Badge variant="accent">{schemaName}</Badge>
        )}
        <span className="font-normal text-fg-muted">
          {records.length} record{records.length !== 1 ? 's' : ''}
        </span>
      </h3>
      <Table>
        <Thead>
          <tr>
            <Th className="w-24">ID</Th>
            {cols.map((c) => (
              <Th key={c}>{c}</Th>
            ))}
            <Th className="w-28">Added</Th>
            <Th className="w-20" />
          </tr>
        </Thead>
        <Tbody>
          {records.map((r) => (
            <Tr key={r.id}>
              <Td>
                <Link
                  to={`/records/${r.id}`}
                  className="text-sm text-accent hover:underline"
                >
                  {r.natural_name ?? (
                    <span className="font-mono">{r.id.slice(0, 8)}</span>
                  )}
                </Link>
              </Td>
              {cols.map((col) => (
                <Td key={col}>
                  <FieldValue value={r.data[col]} />
                </Td>
              ))}
              <Td className="text-fg-muted">{formatDate(r.created_at)}</Td>
              <Td>
                {confirmId === r.id ? (
                  <span className="flex items-center gap-2">
                    <button
                      onClick={() => {
                        onDelete(r.id)
                        setConfirmId(null)
                      }}
                      className="text-xs text-danger font-medium hover:underline"
                    >
                      Confirm
                    </button>
                    <button
                      onClick={() => setConfirmId(null)}
                      className="text-xs text-fg-muted hover:underline"
                    >
                      Cancel
                    </button>
                  </span>
                ) : (
                  <button
                    onClick={() => setConfirmId(r.id)}
                    className="text-xs text-fg-muted hover:text-danger transition-colors"
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
  const { data: collection } = useCollection(record?.dataset_id ?? '')
  const { data: schemas } = useSchemas()
  const { data: workflows } = useWorkflows()
  const { data: parent } = useRecord(record?.parent_record_id)
  const { data: recordJobs } = useJobs(undefined, id)
  const updateRecord = useUpdateRecord()
  const createRecord = useCreateRecord(collection?.name ?? '')
  const deleteRecord = useDeleteRecord(collection?.name ?? '')

  // All children of this record — poll faster while jobs are active
  const hasActiveJobs = (recordJobs ?? []).some(
    (j) => j.status === 'pending' || j.status === 'running',
  )
  const { data: childPage } = useRecords(
    collection?.name ?? '',
    {
      parent_record_id: id,
      limit: 500,
    },
    hasActiveJobs ? 2000 : 5000,
  )

  if (isLoading) return <LoadingState />
  if (error || !record)
    return (
      <ErrorState message={error ? errorMessage(error) : 'Record not found'} />
    )

  const schema = schemas?.find((s) => s.name === record.schema_name)
  const parentSchema = schema?.parent_id
    ? schemas?.find((s) => s.id === schema.parent_id)
    : null
  const children = childPage?.items ?? []
  const childSchemas = schemas?.filter((s) => s.parent_id === schema?.id) ?? []
  const applicableWorkflows = (workflows ?? []).filter(
    (wf) => !wf.record_schema || wf.record_schema === record.schema_name,
  )
  const runWorkflowDef = runWorkflow
    ? (applicableWorkflows.find((wf) => wf.name === runWorkflow) ?? null)
    : null

  function startEditing() {
    setEditValues({ ...record!.data })
    setIsEditing(true)
  }

  function saveEditing() {
    const coerced: Record<string, unknown> = {}
    for (const field of schema?.fields ?? []) {
      const v = editValues[field.name]
      if (v === '' || v === undefined || v === null) continue
      if (field.type === 'integer')
        coerced[field.name] = parseInt(v as string, 10)
      else if (field.type === 'float')
        coerced[field.name] = parseFloat(v as string)
      else coerced[field.name] = v
    }
    updateRecord.mutate(
      { id: record!.id, data: coerced },
      { onSuccess: () => setIsEditing(false) },
    )
  }

  function handleAddChild(
    schemaName: string,
    data: Record<string, unknown>,
    parentRecordId?: string,
  ) {
    createRecord.mutate(
      { schema_name: schemaName, data, parent_record_id: parentRecordId },
      { onSuccess: () => setAddingChild(false) },
    )
  }

  // Group children by schema name for display
  const childrenBySchema = children.reduce<Record<string, CivexRecord[]>>(
    (acc, r) => {
      ;(acc[r.schema_name] ??= []).push(r)
      return acc
    },
    {},
  )

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-2 text-sm text-fg-muted flex-wrap">
        <Link to="/collections" className="hover:text-accent">
          Collections
        </Link>
        <span>/</span>
        {collection && (
          <>
            <Link
              to={`/collections/${record.dataset_id}`}
              className="hover:text-accent"
            >
              {collection.name}
            </Link>
            <span>/</span>
          </>
        )}
        <span className="font-mono text-fg">
          {record.natural_name ?? record.id.slice(0, 8)}
        </span>
      </nav>

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-semibold text-fg">
              {record.natural_name ?? (
                <span className="font-mono">{record.id.slice(0, 8)}</span>
              )}
            </h1>
            {schema ? (
              <Link to={`/schemas/${schema.id}`}>
                <Badge variant="accent">{record.schema_name}</Badge>
              </Link>
            ) : (
              <Badge variant="accent">{record.schema_name}</Badge>
            )}
          </div>
          <p className="mt-1 text-xs text-fg-subtle font-mono">{record.id}</p>
          <p className="mt-1 text-sm text-fg-muted">
            Added {formatDate(record.created_at)}
            {record.created_at !== record.updated_at &&
              ` · Updated ${formatDate(record.updated_at)}`}
          </p>
        </div>
      </div>

      {/* Parent record */}
      {record.parent_record_id && (
        <div className="border border-border rounded-md p-4 bg-canvas-subtle">
          <p className="text-xs font-semibold text-fg-muted uppercase tracking-wide mb-2">
            Parent — {parentSchema?.name ?? 'unknown'}
          </p>
          {parent ? (
            <Link
              to={`/records/${parent.id}`}
              className="text-sm text-accent hover:underline"
            >
              {parent.natural_name ?? (
                <span className="font-mono">{parent.id.slice(0, 8)}</span>
              )}
            </Link>
          ) : (
            <Link
              to={`/records/${record.parent_record_id}`}
              className="font-mono text-sm text-accent hover:underline"
            >
              {record.parent_record_id.slice(0, 8)}
            </Link>
          )}
        </div>
      )}

      {/* Own fields */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-base font-semibold text-fg">Fields</h2>
          {!isEditing && (
            <Button size="sm" onClick={startEditing}>
              Edit
            </Button>
          )}
        </div>

        {isEditing ? (
          <div className="border border-border rounded-md bg-canvas-subtle p-4 space-y-4">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {(schema?.fields ?? []).map((field) => (
                <div key={field.name} className="flex flex-col gap-1">
                  <label className="text-xs font-medium text-fg flex items-center gap-2">
                    <span className="font-mono">{field.name}</span>
                    <Badge variant="accent">{field.type}</Badge>
                    {field.required && (
                      <Badge variant="success">required</Badge>
                    )}
                  </label>
                  <DynamicField
                    field={field}
                    value={editValues[field.name] ?? record.data[field.name]}
                    onChange={(v) =>
                      setEditValues((prev) => ({ ...prev, [field.name]: v }))
                    }
                  />
                </div>
              ))}
            </div>
            {updateRecord.error && (
              <p className="text-xs text-danger">
                {errorMessage(updateRecord.error)}
              </p>
            )}
            <div className="flex gap-2">
              <Button
                variant="primary"
                size="sm"
                onClick={saveEditing}
                disabled={updateRecord.isPending}
              >
                {updateRecord.isPending ? 'Saving…' : 'Save'}
              </Button>
              <Button size="sm" onClick={() => setIsEditing(false)}>
                Cancel
              </Button>
            </div>
          </div>
        ) : Object.keys(record.data).length === 0 ? (
          <p className="text-sm text-fg-muted italic">No field values.</p>
        ) : (
          <div className="grid grid-cols-1 gap-px bg-border border border-border rounded-md overflow-hidden sm:grid-cols-2">
            {(
              schema?.fields ??
              Object.keys(record.data).map((name) => ({
                name,
                type: 'string',
                required: false,
                id: name,
              }))
            ).map((field) => (
              <div key={field.name} className="bg-white px-4 py-3">
                <p className="text-xs text-fg-muted font-mono mb-1 flex items-center gap-2">
                  {field.name}
                  {'type' in field && (
                    <Badge variant="accent">
                      {(field as { type: string }).type}
                    </Badge>
                  )}
                </p>
                <div className="text-sm text-fg">
                  <FieldValue value={record.data[field.name]} />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Children */}
      {(childSchemas.length > 0 ||
        Object.keys(childrenBySchema).length > 0) && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-fg">
              Children
              <span className="ml-2 text-sm font-normal text-fg-muted">
                {children.length} total
              </span>
            </h2>
            {childSchemas.length > 0 && !addingChild && (
              <Button
                variant="primary"
                size="sm"
                onClick={() => setAddingChild(true)}
              >
                + Add record
              </Button>
            )}
          </div>

          {addingChild && collection && schemas && (
            <RecordForm
              schemas={schemas}
              datasetName={collection.name}
              selectableSchemaIds={childSchemas.map((s) => s.id)}
              lockedParentRecordId={record.id}
              onSubmit={handleAddChild}
              onCancel={() => setAddingChild(false)}
              isPending={createRecord.isPending}
              error={
                createRecord.error ? errorMessage(createRecord.error) : null
              }
            />
          )}

          {Object.entries(childrenBySchema).map(([schemaName, recs]) => (
            <ChildTable
              key={schemaName}
              schemaName={schemaName}
              schema={schemas?.find((s) => s.name === schemaName)}
              records={recs}
              onDelete={(childId) => deleteRecord.mutate(childId)}
            />
          ))}
        </div>
      )}

      {applicableWorkflows.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-base font-semibold text-fg">Workflows</h2>
          </div>
          <div className="flex flex-wrap gap-2">
            {applicableWorkflows.map((wf) => (
              <button
                key={wf.name}
                onClick={() => setRunWorkflow(wf.name)}
                className="flex items-center gap-2 px-3 py-2 text-sm border border-border rounded-md hover:bg-canvas-subtle hover:border-accent transition-colors text-fg"
              >
                <span>▶</span>
                <span className="font-mono text-xs">{wf.name}</span>
                {wf.inputs &&
                  Object.values(wf.inputs).some((i) => i.type === 'files') && (
                    <span className="text-xs text-fg-muted">· files</span>
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
      <div className="border border-danger-muted rounded-md">
        <div className="px-4 py-3 border-b border-danger-muted bg-danger-subtle rounded-t-md">
          <h2 className="text-sm font-semibold text-danger">Danger zone</h2>
        </div>
        <div className="px-4 py-3 flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-fg">Delete this record</p>
            <p className="text-xs text-fg-muted">
              Permanently removes this record and all its children.
            </p>
          </div>
          {confirmDelete ? (
            <div className="flex items-center gap-2">
              <span className="text-xs text-fg-muted">Are you sure?</span>
              <Button
                variant="danger"
                size="sm"
                onClick={() =>
                  deleteRecord.mutate(record.id, {
                    onSuccess: () =>
                      navigate(
                        collection
                          ? `/collections/${record.dataset_id}`
                          : '/collections',
                      ),
                  })
                }
                disabled={deleteRecord.isPending}
              >
                {deleteRecord.isPending ? 'Deleting…' : 'Confirm delete'}
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
              Delete record
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}
