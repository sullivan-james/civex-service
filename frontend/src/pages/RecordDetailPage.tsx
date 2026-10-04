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
import { RunWorkflowButton } from '../components/workflows/RunWorkflowButton'
import {
  Badge,
  DetailSkeleton,
  ErrorState,
  Page,
  ConfirmDialog,
  PinButton,
  TabNav,
  TabPanel,
  useTabParam,
} from '../components/ui'
import { ReferencedBy } from '../components/records/ReferencedBy'
import { RecordsExplorer } from '../components/explorer/RecordsExplorer'
import { CollectionTimeZone } from '../components/records/CollectionTimeZone'
import { RecordPageFrame } from '../components/records/RecordPageFrame'
import { fieldSaveErrors } from '../components/records/saveErrors'
import { recordTrail } from '../utils/recordTrail'
import { recordTarget } from '../utils/navTargets'
import { recordRecent } from '../hooks/usePins'
import { formatDate } from '../lib/utils'
import { errorMessage } from '../lib/errors'
import { ApiError } from '../api/client'
import { RecordMissing } from '../components/records/RecordMissing'
import { HIGH_IMPACT_RECORD_THRESHOLD } from '../lib/deleteImpact'
import type { Field as SchemaField } from '../api/schemas'
import JobsTable from '../components/jobs/JobsTable'
import RecordProvenance from '../components/jobs/RecordProvenance'
import { ActivityFeed } from '../components/audit/ActivityFeed'
import { underRecord } from '../utils/auditFilter'
import { RecordFieldGrid } from '../components/records/RecordFieldGrid'

const RECORD_TABS = [
  { id: 'fields' },
  { id: 'contains' },
  { id: 'referenced' },
  { id: 'runs' },
  { id: 'history' },
] as const

export default function RecordDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [tab, setTab] = useTabParam(RECORD_TABS, 'fields')

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
          error && !(error instanceof ApiError && error.status === 404) ? (
            <ErrorState message={errorMessage(error)} />
          ) : (
            <RecordMissing id={id ?? ''} />
          )
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
  const showContains = (hasChildSchemas || descendantTotal > 0) && !!collection
  const shownTab = tab === 'contains' && !showContains ? 'fields' : tab
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
          <>
            <RunWorkflowButton
              workflows={applicableWorkflows}
              recordId={record.id}
              onStarted={() => setTab('runs')}
            />
            <PinButton target={recordTarget(record)} noun="record" size="md" />
          </>
        }
        secondaryActions={[
          {
            label: 'Delete record…',
            variant: 'danger' as const,
            onClick: () => setConfirmDelete(true),
          },
        ]}
        tabs={
          <TabNav
            label="Record"
            value={shownTab}
            onChange={setTab}
            tabs={[
              { id: 'fields' as const, label: 'Fields' },
              ...(showContains
                ? [
                    {
                      id: 'contains' as const,
                      label: `Contains (${descendantTotal.toLocaleString()})`,
                    },
                  ]
                : []),
              { id: 'referenced' as const, label: 'Referenced by' },
              { id: 'runs' as const, label: 'Runs' },
              { id: 'history' as const, label: 'History' },
            ]}
          />
        }
        meta={
          <>
            Added {formatDate(record.created_at)}
            {record.created_at !== record.updated_at &&
              ` · Updated ${formatDate(record.updated_at)}`}
          </>
        }
      >
        <TabPanel id="fields" value={shownTab}>
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
        </TabPanel>

        <TabPanel id="contains" value={shownTab}>
          {collection && (
            <RecordsExplorer
              dataset={collection.name}
              root={{ id: record.id }}
              pollMs={hasActiveJobs ? 2000 : 5000}
            />
          )}
        </TabPanel>

        <TabPanel id="referenced" value={shownTab}>
          <ReferencedBy recordId={record.id} />
        </TabPanel>

        <TabPanel id="runs" value={shownTab}>
          <div className="space-y-6">
            <JobsTable recordId={record.id} ns="runs." />
            <RecordProvenance recordId={record.id} />
          </div>
        </TabPanel>

        <TabPanel id="history" value={shownTab}>
          <ActivityFeed
            scope={underRecord(record.id)}
            ns="history."
            emptyMessage="Changes to this record, and to everything beneath it, will appear here."
          />
        </TabPanel>

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
