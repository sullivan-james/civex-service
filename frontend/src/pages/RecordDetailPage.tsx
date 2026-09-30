import { useState } from 'react'
import { Link, useParams, useNavigate } from 'react-router'
import {
  useRecord,
  useRecords,
  useUpdateRecord,
  useCreateRecord,
  useDeleteRecord,
} from '../hooks/useRecords'
import { recordsApi } from '../api/records'
import { useCollection } from '../hooks/useCollections'
import { useSchemas } from '../hooks/useSchemas'
import { useWorkflows, useJobs } from '../hooks/useWorkflows'
import { WorkflowRunModal } from '../components/workflows/WorkflowRunModal'
import {
  Badge,
  Button,
  Field,
  Table,
  Thead,
  Th,
  Tbody,
  Tr,
  Td,
  DetailSkeleton,
  ErrorState,
  FormError,
  Page,
  ConfirmDialog,
  Section,
  CollapsibleSection,
} from '../components/ui'
import { X, Play } from '../components/ui/icons'
import { DynamicField } from '../components/records/DynamicField'
import { RecordForm } from '../components/records/RecordForm'
import { formatDate } from '../lib/utils'
import { displayLabel } from '../utils/naming'
import { errorMessage } from '../lib/errors'
import { fieldErrorInfo } from '../utils/validationErrors'
import { HIGH_IMPACT_RECORD_THRESHOLD } from '../lib/deleteImpact'
import type { Schema, Field as SchemaField } from '../api/schemas'
import type { CivexRecord } from '../api/records'
import JobsTable from '../components/jobs/JobsTable'
import RecordProvenance from '../components/jobs/RecordProvenance'
import { AuditTrail } from '../components/audit/AuditTrail'
import { describeAuditEntry as describeRecordAuditEntry } from '../utils/recordAudit'
import { FieldValue } from '../components/records/FieldValue'

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
  const cols = schema?.fields.filter((f) => f.type !== 'file') ?? []
  const [confirmId, setConfirmId] = useState<string | null>(null)
  const confirmRecord = records.find((r) => r.id === confirmId) ?? null

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold text-fg flex items-center gap-2">
        {schema ? (
          <Link to={`/schemas/${schema.id}`}>
            <Badge variant="accent">
              {displayLabel(schemaName, schema.label)}
            </Badge>
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
              <Th key={c.name} title={c.name}>
                {displayLabel(c.name, c.label)}
              </Th>
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
                <Td key={col.name}>
                  <FieldValue
                    value={r.data[col.name]}
                    field={col}
                    referenceLabels={r.reference_labels}
                  />
                </Td>
              ))}
              <Td className="text-fg-muted">{formatDate(r.created_at)}</Td>
              <Td>
                <button
                  onClick={() => setConfirmId(r.id)}
                  className="text-xs text-fg-muted hover:text-danger transition-colors"
                  title="Delete record"
                >
                  <X size={14} />
                </button>
              </Td>
            </Tr>
          ))}
        </Tbody>
      </Table>
      {confirmRecord && (
        <ConfirmDialog
          title="Delete record"
          body={`Delete ${confirmRecord.natural_name ?? `record ${confirmRecord.id.slice(0, 8)}`}? It'll move to Recently Deleted — restore any time before it's permanently purged.`}
          confirmLabel="Delete record"
          variant="danger"
          onConfirm={() => {
            onDelete(confirmRecord.id)
            setConfirmId(null)
          }}
          onClose={() => setConfirmId(null)}
        />
      )}
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

  const breadcrumbs = [{ label: 'Collections', to: '/collections' }]

  if (isLoading)
    return (
      <Page
        breadcrumbs={breadcrumbs}
        loading={<DetailSkeleton metadataRows={4} sections={2} />}
      />
    )
  if (error || !record)
    return (
      <Page
        breadcrumbs={breadcrumbs}
        error={
          <ErrorState
            message={error ? errorMessage(error) : 'Record not found'}
          />
        }
      />
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
  const updateRecordErrors = fieldErrorInfo(
    updateRecord.error,
    (schema?.fields ?? []).map((f) => f.name),
    errorMessage,
  )

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
    <Page
      breadcrumbs={[
        ...breadcrumbs,
        ...(collection
          ? [
              {
                label: collection.name,
                to: `/collections/${record.dataset_id}`,
              },
            ]
          : []),
        { label: record.natural_name ?? record.id.slice(0, 8) },
      ]}
      title={
        <span className="inline-flex items-center gap-2">
          {record.natural_name ?? (
            <span className="font-mono">{record.id.slice(0, 8)}</span>
          )}
          {schema ? (
            <Link to={`/schemas/${schema.id}`}>
              <Badge variant="accent">{record.schema_name}</Badge>
            </Link>
          ) : (
            <Badge variant="accent">{record.schema_name}</Badge>
          )}
        </span>
      }
      description={
        <>
          <p className="text-xs text-fg-subtle font-mono">{record.id}</p>
          <p className="mt-1">
            Added {formatDate(record.created_at)}
            {record.created_at !== record.updated_at &&
              ` · Updated ${formatDate(record.updated_at)}`}
          </p>
        </>
      }
    >
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
      <Section
        title="Fields"
        action={
          !isEditing && (
            <Button size="sm" onClick={startEditing}>
              Edit
            </Button>
          )
        }
      >
        {isEditing ? (
          <div className="space-y-4">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {(schema?.fields ?? []).map((field) => (
                <Field
                  key={field.name}
                  label={
                    <span className="flex items-center gap-2">
                      <span title={field.name}>
                        {displayLabel(field.name, field.label)}
                      </span>
                      <Badge variant="accent">{field.type}</Badge>
                      {field.required && (
                        <Badge variant="success">required</Badge>
                      )}
                    </span>
                  }
                  error={updateRecordErrors.fieldErrors[field.name]}
                >
                  <DynamicField
                    field={field}
                    value={editValues[field.name] ?? record.data[field.name]}
                    onChange={(v) =>
                      setEditValues((prev) => ({ ...prev, [field.name]: v }))
                    }
                  />
                </Field>
              ))}
            </div>
            <FormError
              message={updateRecordErrors.generalMessage}
              technical={updateRecordErrors.technical}
            />
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
                label: null,
                type: 'string',
                required: false,
                id: name,
              }))
            ).map((field) => (
              <div key={field.name} className="bg-canvas px-4 py-3">
                <p
                  className="text-xs text-fg-muted mb-1 flex items-center gap-2"
                  title={field.name}
                >
                  {displayLabel(field.name, field.label)}
                  {'type' in field && (
                    <Badge variant="accent">
                      {(field as { type: string }).type}
                    </Badge>
                  )}
                </p>
                <div className="text-sm text-fg">
                  <FieldValue
                    value={record.data[field.name]}
                    field={field as SchemaField}
                    referenceLabels={record.reference_labels}
                  />
                </div>
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* Children */}
      {(childSchemas.length > 0 ||
        Object.keys(childrenBySchema).length > 0) && (
        <Section
          title="Children"
          count={children.length}
          action={
            childSchemas.length > 0 &&
            !addingChild && (
              <Button
                variant="primary"
                size="sm"
                onClick={() => setAddingChild(true)}
              >
                + Add record
              </Button>
            )
          }
        >
          <div className="space-y-4">
            {addingChild && collection && schemas && (
              <RecordForm
                schemas={schemas}
                datasetName={collection.name}
                selectableSchemaIds={childSchemas.map((s) => s.id)}
                lockedParentRecordId={record.id}
                onSubmit={handleAddChild}
                onCancel={() => setAddingChild(false)}
                isPending={createRecord.isPending}
                error={createRecord.error}
              />
            )}

            {Object.entries(childrenBySchema).map(([schemaName, recs]) => (
              <ChildTable
                key={schemaName}
                schemaName={schemaName}
                schema={schemas?.find((s) => s.name === schemaName)}
                records={recs}
                onDelete={(childId) =>
                  deleteRecord.mutate({
                    id: childId,
                    undo: () => recordsApi.restore(childId),
                  })
                }
              />
            ))}
          </div>
        </Section>
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
                <Play size={12} />
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

      <RecordProvenance recordId={record.id} />

      <AuditTrail
        queryKey={['records', record.id, 'audit']}
        fetchPage={(offset, limit) =>
          recordsApi.audit(record.id, offset, limit)
        }
        describeEntry={(entry) => describeRecordAuditEntry(entry, schema)}
        emptyMessage="Changes to this record will appear here."
      />

      <CollapsibleSection title="Runs">
        <JobsTable recordId={record.id} />
      </CollapsibleSection>

      {/* Danger zone */}
      <div className="border border-danger-muted rounded-md">
        <div className="px-4 py-3 border-b border-danger-muted bg-danger-subtle rounded-t-md">
          <h2 className="text-sm font-semibold text-danger">Danger zone</h2>
        </div>
        <div className="px-4 py-3 flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-fg">Delete this record</p>
            <p className="text-xs text-fg-muted">
              Moves this record (and its children) to Recently Deleted — restore
              it any time before it's permanently purged.
            </p>
          </div>
          <Button
            variant="danger"
            size="sm"
            onClick={() => setConfirmDelete(true)}
          >
            Delete record
          </Button>
        </div>
      </div>

      {confirmDelete && (
        <ConfirmDialog
          title="Delete record"
          body={
            children.length > 0
              ? `Delete ${record.natural_name ?? `record ${record.id.slice(0, 8)}`}? This also deletes its ${children.length.toLocaleString()} child record${children.length === 1 ? '' : 's'}. They'll move to Recently Deleted — restore any time before it's permanently purged.`
              : `Delete ${record.natural_name ?? `record ${record.id.slice(0, 8)}`}? It'll move to Recently Deleted — restore any time before it's permanently purged.`
          }
          confirmLabel={
            children.length > 0
              ? `Delete record and ${children.length.toLocaleString()} child record${children.length === 1 ? '' : 's'}`
              : 'Delete record'
          }
          variant="danger"
          typedConfirmationValue={
            children.length > HIGH_IMPACT_RECORD_THRESHOLD
              ? (record.natural_name ?? record.id.slice(0, 8))
              : undefined
          }
          warning={
            deleteRecord.error ? errorMessage(deleteRecord.error) : undefined
          }
          isPending={deleteRecord.isPending}
          onConfirm={() =>
            deleteRecord.mutate(
              { id: record.id, undo: () => recordsApi.restore(record.id) },
              {
                onSuccess: () =>
                  navigate(
                    collection
                      ? `/collections/${record.dataset_id}`
                      : '/collections',
                  ),
              },
            )
          }
          onClose={() => setConfirmDelete(false)}
        />
      )}
    </Page>
  )
}
