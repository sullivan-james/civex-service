import { useEffect, useState } from 'react'
import { Link, useParams, useNavigate } from 'react-router'
import {
  useRecord,
  useRecordCounts,
  useRecordFileSaver,
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
import { FileAccessActions } from '../components/files/FileAccessActions'
import { schemaTreeHasFiles } from '../utils/hierarchy'
import { useAvailableExports } from '../hooks/useExportDefinitions'
import { describeDefinition } from '../utils/exportBuilder'
import {
  Button,
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
import { displayLabel } from '../utils/naming'
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
import { DeletedFieldValues } from '../components/records/DeletedFieldValues'
import { RecordFieldGrid } from '../components/records/RecordFieldGrid'
import { usePermissions } from '../hooks/useMe'
import { MergeView } from '../components/sync/MergeView'
import { ReviewStepper } from '../components/sync/ReviewStepper'
import { RecordConflicts } from '../components/sync/RecordConflicts'
import { OrphanBanner } from '../components/records/OrphanBanner'
import { layoutConflicts } from '../utils/syncConflicts'
import {
  useConflictsAbout,
  useMergeConflicts,
  useResolveConflict,
} from '../hooks/useRemote'
import { Slot } from '../components/host/Slot'
import { NotesPanel } from '../components/notes/NotesPanel'

/** How many fields a record with things inside it shows before "Show all". */
const FIELDS_FIRST = 6

const RECORD_TABS = [
  { id: 'fields' },
  { id: 'resolve' },
  { id: 'contains' },
  { id: 'notes' },
  { id: 'referenced' },
  { id: 'runs' },
  { id: 'history' },
] as const

export default function RecordDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [showDeleted, setShowDeleted] = useState(false)
  const [allFieldsShown, setAllFieldsShown] = useState(false)
  const [tab, setTab] = useTabParam(RECORD_TABS, 'fields')

  const { data: record, isLoading, error } = useRecord(id, 3000)
  const { data: collection } = useCollection(record?.dataset_id ?? '')
  const { can, why } = usePermissions()
  const { data: schemas } = useSchemas()
  const { data: presets } = useAvailableExports(
    record ? { schema: record.schema_name } : null,
  )
  const { data: workflows } = useWorkflows()
  const { data: recordJobs } = useJobs(undefined, id)
  const [savingField, setSavingField] = useState<string | null>(null)
  // quiet: the field itself shows the outcome (new value, or the error under it)
  const updateRecord = useUpdateRecord({ quiet: true })
  // A file chosen in a field is stored and the record saved as one request.
  const saveFile = useRecordFileSaver(id ?? '')
  const deleteRecord = useDeleteRecord(collection?.name ?? '')
  // What the authority did not take of this record's changes (nothing, and not
  // even asked for, while there is nothing to review).
  const conflictsAbout = useConflictsAbout(id ?? '')
  const settleConflict = useResolveConflict()
  // The Resolve tab's rows: the open ones and those settled since it opened.
  const { data: mergeConflicts } = useMergeConflicts(
    id ?? '',
    tab === 'resolve',
  )

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
  // The Resolve tab is there while there is something to settle, and stays while
  // the rows just settled are still on screen.
  const showResolve =
    conflictsAbout.length > 0 || (mergeConflicts?.length ?? 0) > 0
  // What a record contains is under its fields, not a tab of its own; an
  // old `?tab=contains` link lands there.
  const shownTab =
    tab === 'contains' || (tab === 'resolve' && !showResolve) ? 'fields' : tab
  // A record with things inside it is mostly visited to reach them: its
  // fields fold to the first few, with the rest one click away. Never
  // while a field needs attention (a clash to settle, a save refused).
  const allFields: SchemaField[] =
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
  const canFold =
    showContains &&
    allFields.length > FIELDS_FIRST + 2 &&
    conflictsAbout.length === 0 &&
    !updateRecord.error
  const foldFields = canFold && !allFieldsShown
  // A failed save is shown under the field it was for.
  const saveErrors = fieldSaveErrors(
    updateRecord.error,
    (schema?.fields ?? []).map((f) => f.name),
    savingField,
  )

  // Where the conflicts are shown: a clash under its field, a refused change
  // beside the fields it set, the rest in the banner.
  const conflictLayout = layoutConflicts(
    conflictsAbout,
    (schema?.fields ?? []).map((f) => ({ id: f.id, name: f.name })),
  )

  // PATCH replaces the whole data object, so send this field on top of the
  // rest; `undefined` drops it.
  function saveField(name: string, value: unknown | undefined) {
    setSavingField(name)
    const next = { ...record!.data }
    if (value === undefined) delete next[name]
    else next[name] = value
    updateRecord.mutate(
      { id: record!.id, data: next },
      {
        // Setting a field that clashed by hand settles the clash: the person
        // has chosen, and it is an edit like any other.
        onSuccess: () => {
          for (const c of conflictLayout.clashes.get(name) ?? [])
            settleConflict.mutate({ id: c.id, take: 'edited' })
        },
      },
    )
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
        hierarchy={false}
        path={record.ancestors ?? []}
        current={record.natural_name ?? record.id.slice(0, 8)}
        currentSchema={record.schema_name}
        title={
          // What kind of thing this is comes first, then which one.
          <span className="flex flex-col gap-1">
            <span className="text-sm font-medium text-fg-muted">
              {schema ? (
                <Link className="hover:underline" to={`/schemas/${schema.id}`}>
                  {displayLabel(schema.name, schema.label)}
                </Link>
              ) : (
                displayLabel(record.schema_name)
              )}
            </span>
            <span>
              {record.natural_name ?? (
                <span className="font-mono">{record.id.slice(0, 8)}</span>
              )}
            </span>
          </span>
        }
        action={
          <>
            <Slot name="record.header" props={{ recordId: record.id }} />
            {!!record.open_notes && (
              <Button
                size="sm"
                variant="ghost"
                to={`/records/${record.id}?tab=notes`}
                title="Threads of notes not yet resolved"
              >
                {record.open_notes === 1
                  ? '1 open note'
                  : `${record.open_notes} open notes`}
              </Button>
            )}
            {/* Every file under this record, by name and folder: an Encounter
                holds none itself, but its Recordings and Selections do. */}
            {schema && schemas && schemaTreeHasFiles(schema, schemas) && (
              <FileAccessActions
                selection={{ within: record.id }}
                folderName={record.natural_name ?? record.id.slice(0, 8)}
                // The exports saved with this kind of record (or one above it),
                // run on everything inside this one.
                presets={(presets ?? []).map((p) => ({
                  label: p.name,
                  hint: describeDefinition(p, schemas),
                  selection: {
                    export: `${p.schema_name}/${p.name}`,
                    within: record.id,
                  },
                  folderName: `${record.natural_name ?? record.id.slice(0, 8)}-${p.name}`,
                  definition: p,
                }))}
                scopeSchema={record.schema_name}
                builderTo={`/exports?schema=${encodeURIComponent(schema.name)}`}
                size="md"
              />
            )}
            <RunWorkflowButton
              workflows={applicableWorkflows}
              recordId={record.id}
              onStarted={() => setTab('runs')}
            />
            <PinButton target={recordTarget(record)} noun="record" size="md" />
          </>
        }
        secondaryActions={[
          // The files of this record and of what is inside it.
          ...(showContains
            ? [{ label: 'Files', onClick: () => navigate('?show=files') }]
            : []),
          // Which fields a kind has is the schema's page, not a record's.
          ...(schema
            ? [
                {
                  label: 'Edit fields',
                  onClick: () => navigate(`/schemas/${schema.id}`),
                },
              ]
            : []),
          // Rarely wanted: the values of fields deleted since.
          ...((record.deleted_fields ?? []).length > 0
            ? [
                {
                  label: showDeleted ? 'Hide deleted fields' : 'Deleted fields',
                  onClick: () => setShowDeleted((on) => !on),
                },
              ]
            : []),
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
              ...(showResolve
                ? [
                    {
                      id: 'resolve' as const,
                      label: `Resolve (${conflictsAbout.length})`,
                    },
                  ]
                : []),
              {
                id: 'notes' as const,
                label: record.open_notes
                  ? `Notes (${record.open_notes})`
                  : 'Notes',
              },
              { id: 'referenced' as const, label: 'Linked from' },
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
        <ReviewStepper recordId={record.id} active={shownTab === 'resolve'} />
        <OrphanBanner record={record} onDelete={() => setConfirmDelete(true)} />
        {shownTab === 'fields' && (
          <RecordConflicts
            layout={conflictLayout}
            onResolve={() => setTab('resolve')}
          />
        )}
        <TabPanel id="resolve" value={shownTab}>
          <MergeView
            recordId={record.id}
            fields={schema?.fields ?? []}
            data={record.data}
            conflicts={mergeConflicts ?? []}
            referenceLabels={record.reference_labels}
            referenceCollections={record.reference_collections}
            onSave={saveField}
            onClose={() => setTab('fields')}
          />
        </TabPanel>
        <TabPanel id="fields" value={shownTab}>
          <UploadCollectionContext.Provider value={record.dataset_id}>
            <div className="mb-3">
              <RecordStorageSummary
                recordId={record.id}
                name={record.natural_name ?? record.id.slice(0, 8)}
                filesHref={showContains ? '?show=files' : undefined}
              />
            </div>
            <RecordFieldGrid
              fields={foldFields ? allFields.slice(0, FIELDS_FIRST) : allFields}
              data={record.data}
              computed={{
                values: record.derived,
                errors: record.formula_errors,
              }}
              referenceLabels={record.reference_labels}
              referenceCollections={record.reference_collections}
              onSave={saveField}
              fileSaver={saveFile}
              readOnly={
                can('write_records', record.dataset_id)
                  ? undefined
                  : why('write_records')
              }
              errors={saveErrors}
              onDismissError={() => updateRecord.reset()}
              marked={conflictLayout.marked}
            />
            {canFold && (
              <Button
                size="sm"
                variant="ghost"
                className="mt-2"
                aria-expanded={allFieldsShown}
                onClick={() => setAllFieldsShown((on) => !on)}
              >
                {allFieldsShown
                  ? 'Show fewer'
                  : `Show all ${allFields.length} fields`}
              </Button>
            )}
            {showDeleted && (
              <DeletedFieldValues fields={record.deleted_fields ?? []} />
            )}
          </UploadCollectionContext.Provider>
          {showContains && collection && (
            <section
              aria-label="Inside this record"
              className="mt-8 space-y-3 border-t border-border pt-6"
            >
              <RecordsExplorer
                dataset={collection.name}
                root={{ id: record.id }}
                pollMs={hasActiveJobs ? 2000 : 5000}
              />
            </section>
          )}
        </TabPanel>

        <TabPanel id="notes" value={shownTab}>
          <NotesPanel recordId={record.id} collectionId={record.dataset_id} />
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
