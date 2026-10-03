import { useEffect, useState } from 'react'
import { Link, useParams, useNavigate } from 'react-router'
import {
  useRecord,
  useRecordCounts,
  useUpdateRecord,
  useDeleteRecord,
} from '../hooks/useRecords'
import { recordsApi } from '../api/records'
import { useCollection } from '../hooks/useCollections'
import { UploadCollectionContext } from '../hooks/uploadCollection'
import { RecordStorageSummary } from '../components/records/RecordStorageSummary'
import { useSchemas } from '../hooks/useSchemas'
import { useWorkflows, useJobs } from '../hooks/useWorkflows'
import { WorkflowRunModal } from '../components/workflows/WorkflowRunModal'
import {
  Badge,
  Button,
  DetailSkeleton,
  ErrorState,
  Page,
  ConfirmDialog,
  Section,
  CollapsibleSection,
  PinButton,
} from '../components/ui'
import { Play } from '../components/ui/icons'
import { ReferencedBy } from '../components/records/ReferencedBy'
import { ContainsPreview } from '../components/records/ContainsPreview'
import { CollectionTimeZone } from '../components/records/CollectionTimeZone'
import { RecordPageFrame } from '../components/records/RecordPageFrame'
import { fieldSaveErrors } from '../components/records/saveErrors'
import { recordTrail } from '../utils/recordTrail'
import { recordTarget } from '../utils/navTargets'
import { recordRecent } from '../hooks/usePins'
import { formatDate } from '../lib/utils'
import { errorMessage } from '../lib/errors'
import { HIGH_IMPACT_RECORD_THRESHOLD } from '../lib/deleteImpact'
import type { Field as SchemaField } from '../api/schemas'
import JobsTable from '../components/jobs/JobsTable'
import RecordProvenance from '../components/jobs/RecordProvenance'
import { AuditTrail } from '../components/audit/AuditTrail'
import { describeAuditEntry as describeRecordAuditEntry } from '../utils/recordAudit'
import { RecordFieldGrid } from '../components/records/RecordFieldGrid'

export default function RecordDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [runWorkflow, setRunWorkflow] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const { data: record, isLoading, error } = useRecord(id, 3000)
  const { data: collection } = useCollection(record?.dataset_id ?? '')
  const { data: schemas } = useSchemas()
  const { data: workflows } = useWorkflows()
  const { data: recordJobs } = useJobs(undefined, id)
  const [savingField, setSavingField] = useState<string | null>(null)
  // quiet: the field itself shows the outcome (new value, or the error under it)
  const updateRecord = useUpdateRecord({ quiet: true })
  const deleteRecord = useDeleteRecord(collection?.name ?? '')

  // Everything below this record (children, grandchildren, …) -- the
  // explorer lists it; this total is what deleting the record would take too.
  const { data: descendantCounts } = useRecordCounts(collection?.name ?? '', {
    within: id,
  })
  const descendantTotal = Object.values(descendantCounts ?? {}).reduce(
    (sum, n) => sum + n,
    0,
  )
  const hasActiveJobs = (recordJobs ?? []).some(
    (j) => j.status === 'pending' || j.status === 'running',
  )

  // Opened records feed Home's "pick up where you left off".
  const recordKey = record?.id
  const recordLabel = record?.natural_name
  useEffect(() => {
    if (recordKey && record) recordRecent(recordTarget(record))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recordKey, recordLabel])

  const breadcrumbs = recordTrail(undefined)

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
  const hasChildSchemas = (schemas ?? []).some(
    (s) => s.parent_id === schema?.id,
  )
  const applicableWorkflows = (workflows ?? []).filter(
    (wf) => !wf.record_schema || wf.record_schema === record.schema_name,
  )
  const runWorkflowDef = runWorkflow
    ? (applicableWorkflows.find((wf) => wf.name === runWorkflow) ?? null)
    : null
  // A failed save is shown under the field it was for.
  const saveErrors = fieldSaveErrors(
    updateRecord.error,
    (schema?.fields ?? []).map((f) => f.name),
    savingField,
  )

  // PATCH replaces the whole data object, so send this field on top of the
  // rest; `undefined` drops it.
  function saveField(name: string, value: unknown | undefined) {
    setSavingField(name)
    const next = { ...record!.data }
    if (value === undefined) delete next[name]
    else next[name] = value
    updateRecord.mutate({ id: record!.id, data: next })
  }

  return (
    <CollectionTimeZone
      timeZone={collection?.timezone}
      collection={collection?.name}
    >
      <RecordPageFrame
        collection={collection?.name}
        collectionId={record.dataset_id}
        recordId={record.id}
        path={record.ancestors ?? []}
        current={record.natural_name ?? record.id.slice(0, 8)}
        currentSchema={record.schema_name}
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
        action={
          <PinButton target={recordTarget(record)} noun="record" size="md" />
        }
        description={
          <>
            Added {formatDate(record.created_at)}
            {record.created_at !== record.updated_at &&
              ` · Updated ${formatDate(record.updated_at)}`}
          </>
        }
      >
        {/* Own fields */}
        <Section title="Fields">
          <UploadCollectionContext.Provider value={record.dataset_id}>
            <div className="mb-3">
              <RecordStorageSummary data={record.data} />
            </div>
            <RecordFieldGrid
              fields={
                schema?.fields ??
                Object.keys(record.data).map(
                  (name) =>
                    ({
                      name,
                      label: null,
                      type: 'string',
                      required: false,
                      id: name,
                    }) as SchemaField,
                )
              }
              data={record.data}
              referenceLabels={record.reference_labels}
              referenceCollections={record.reference_collections}
              onSave={saveField}
              errors={saveErrors}
              onDismissError={() => updateRecord.reset()}
            />
          </UploadCollectionContext.Provider>
        </Section>

        {(hasChildSchemas || descendantTotal > 0) && collection && (
          <Section title="Contains" count={descendantTotal}>
            <ContainsPreview
              record={record}
              collection={collection.name}
              collectionId={record.dataset_id}
              pollMs={hasActiveJobs ? 2000 : 5000}
            />
          </Section>
        )}

        <ReferencedBy recordId={record.id} />

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
                    Object.values(wf.inputs).some(
                      (i) => i.type === 'files',
                    ) && <span className="text-xs text-fg-muted">· files</span>}
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
                Moves this record (and everything under it) to Recently Deleted
                — restore it any time before it's permanently purged.
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
              descendantTotal > 0
                ? `Delete ${record.natural_name ?? `record ${record.id.slice(0, 8)}`}? This also deletes its ${descendantTotal.toLocaleString()} child record${descendantTotal === 1 ? '' : 's'}. They'll move to Recently Deleted — restore any time before it's permanently purged.`
                : `Delete ${record.natural_name ?? `record ${record.id.slice(0, 8)}`}? It'll move to Recently Deleted — restore any time before it's permanently purged.`
            }
            confirmLabel={
              descendantTotal > 0
                ? `Delete record and ${descendantTotal.toLocaleString()} child record${descendantTotal === 1 ? '' : 's'}`
                : 'Delete record'
            }
            variant="danger"
            typedConfirmationValue={
              descendantTotal > HIGH_IMPACT_RECORD_THRESHOLD
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
      </RecordPageFrame>
    </CollectionTimeZone>
  )
}
