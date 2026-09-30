import { useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router'
import { errorMessage } from '../lib/errors'
import { schemaRecordsPath } from '../utils/explorerState'
import { HIGH_IMPACT_RECORD_THRESHOLD } from '../lib/deleteImpact'
import { schemasApi } from '../api/schemas'
import {
  useSchema,
  useSchemaDeleteImpact,
  useUpdateSchema,
  useDeleteSchema,
  useSchemas,
} from '../hooks/useSchemas'
import { usePlugins } from '../hooks/usePlugins'
import {
  Button,
  DetailSkeleton,
  Skeleton,
  ErrorState,
  Field,
  Input,
  ConfirmDialog,
  Page,
  FormGrid,
  NameLabelFields,
  Section,
} from '../components/ui'
import { displayLabel, nameError } from '../utils/naming'
import { Upload } from '../components/ui/icons'
import { SchemaFieldsSection } from '../components/schemas/SchemaFieldsSection'
import { AuditTrail } from '../components/audit/AuditTrail'
import { describeAuditEntry as describeSchemaAuditEntry } from '../utils/schemaAudit'
import { WorkflowsPanel } from '../components/workflows/WorkflowsPanel'
import { WorkflowSummaryModal } from '../components/workflows/WorkflowSummaryModal'
import { WorkflowRunModal } from '../components/workflows/WorkflowRunModal'
import type { Workflow } from '../api/workflows'

function describeDeleteImpact(childCount: number, recordCount: number): string {
  const records = `${recordCount.toLocaleString()} record${recordCount === 1 ? '' : 's'}`
  const children = `${childCount} child type${childCount === 1 ? '' : 's'}`
  if (childCount > 0 && recordCount > 0) {
    return `Deleting it will also delete ${records} typed by it. This record type has ${children} that inherit from it — they'll keep working, pointing at a hidden parent, until it's restored.`
  }
  if (childCount > 0) {
    return `This record type has ${children} that inherit from it — they'll keep working, pointing at a hidden parent, until it's restored.`
  }
  if (recordCount > 0) {
    return `Deleting it will also delete ${records}.`
  }
  return "It moves to Recently Deleted and can be restored until it's purged."
}

// --- Inline metadata editor ---

function MetaEditor({
  schema,
  onDone,
}: {
  schema: { name: string; label: string | null; description: string | null }
  onDone: () => void
}) {
  const [name, setName] = useState(schema.name)
  const [label, setLabel] = useState(schema.label ?? '')
  const [description, setDescription] = useState(schema.description ?? '')
  const updateSchema = useUpdateSchema(schema.name)

  function handleSave() {
    const trimmedName = name.trim()
    if (nameError(trimmedName)) return
    const trimmedLabel = label.trim()
    const body: { rename?: string; label?: string; description?: string } = {}
    if (trimmedName !== schema.name) body.rename = trimmedName
    // '' clears the label; omitting the key leaves it untouched.
    if (trimmedLabel !== (schema.label ?? '')) body.label = trimmedLabel
    if (description !== (schema.description ?? ''))
      body.description = description
    if (!Object.keys(body).length) {
      onDone()
      return
    }
    updateSchema.mutate(body, { onSuccess: onDone })
  }

  return (
    <div className="border border-border rounded-md p-4 bg-canvas-subtle mb-4 flex flex-col gap-3">
      <FormGrid>
        <NameLabelFields
          kind="Schema"
          value={{ label, name }}
          onChange={(next) => {
            setLabel(next.label)
            setName(next.name)
          }}
          deriveName={false}
          onEnter={handleSave}
        />
      </FormGrid>
      <Field label="Description">
        <Input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="No description"
        />
      </Field>
      {updateSchema.error && (
        <p className="text-xs text-danger">
          {errorMessage(updateSchema.error)}
        </p>
      )}
      <div className="flex gap-2">
        <Button
          variant="primary"
          size="sm"
          onClick={handleSave}
          disabled={updateSchema.isPending}
        >
          {updateSchema.isPending ? 'Saving…' : 'Save'}
        </Button>
        <Button size="sm" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </div>
  )
}

// --- Main page ---

export default function SchemaDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [editing, setEditing] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  // Fetch by UUID — name changes don't affect the URL
  const { data: schema, isLoading, error } = useSchema(id!)
  const { data: allSchemas } = useSchemas()
  const { data: deleteImpact, isLoading: deleteImpactLoading } =
    useSchemaDeleteImpact(schema?.name ?? '', confirmDelete)
  const deleteSchema = useDeleteSchema()
  const { data: pluginList } = usePlugins()
  const [summaryTarget, setSummaryTarget] = useState<Workflow | null>(null)
  const [runTarget, setRunTarget] = useState<Workflow | null>(null)

  const breadcrumbs = [{ label: 'Schemas', to: '/schemas' }]

  if (isLoading)
    return (
      <Page
        breadcrumbs={breadcrumbs}
        loading={
          <>
            <DetailSkeleton metadataRows={0} sections={0} />
            <div className="flex flex-col gap-2">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          </>
        }
      />
    )
  if (error || !schema)
    return (
      <Page
        breadcrumbs={breadcrumbs}
        error={
          <ErrorState
            message={error ? errorMessage(error) : 'Schema not found'}
          />
        }
      />
    )

  const parentSchema = schema.parent_id
    ? allSchemas?.find((s) => s.id === schema.parent_id)
    : null

  return (
    <Page
      breadcrumbs={[
        ...breadcrumbs,
        { label: displayLabel(schema.name, schema.label) },
      ]}
      title={displayLabel(schema.name, schema.label)}
      description={
        <>
          <p
            className="font-mono text-xs text-fg-subtle"
            title="Schema name — what workflows and CSV headers reference"
          >
            {schema.name}
          </p>
          <p className="mt-1">
            {schema.description ?? (
              <span className="italic">No description</span>
            )}
          </p>
          {parentSchema && (
            <p className="mt-1">
              Inherits from{' '}
              <Link
                to={`/schemas/${parentSchema.id}`}
                className="text-accent hover:underline"
              >
                {parentSchema.name}
              </Link>
            </p>
          )}
        </>
      }
      action={
        !editing && (
          <div className="flex items-center gap-2">
            <Link to={`/schemas/${schema.id}/import`}>
              <Button size="sm" variant="primary">
                <Upload size={14} /> Import data
              </Button>
            </Link>
            <Link to={schemaRecordsPath(schema.id)}>
              <Button size="sm">Browse records</Button>
            </Link>
            <Button size="sm" onClick={() => setEditing(true)}>
              Edit
            </Button>
          </div>
        )
      }
    >
      {editing && (
        <MetaEditor schema={schema} onDone={() => setEditing(false)} />
      )}

      <SchemaFieldsSection schema={schema} allSchemas={allSchemas} />

      <Section title="Automations">
        <WorkflowsPanel
          schemaName={schema.name}
          onRun={(wf) => setRunTarget(wf)}
          onView={(wf) => setSummaryTarget(wf)}
        />
      </Section>

      {summaryTarget && (
        <WorkflowSummaryModal
          workflow={summaryTarget}
          plugins={pluginList ?? []}
          onClose={() => setSummaryTarget(null)}
        />
      )}

      {runTarget && (
        <WorkflowRunModal
          workflow={runTarget}
          onClose={() => setRunTarget(null)}
        />
      )}

      <AuditTrail
        queryKey={['schemas', schema.name, 'audit']}
        fetchPage={(offset, limit) =>
          schemasApi.getAudit(schema.name, offset, limit)
        }
        describeEntry={describeSchemaAuditEntry}
        emptyMessage="Changes to this schema and its fields will appear here."
      />

      {/* Danger zone */}
      <div className="border border-danger-muted rounded-md">
        <div className="px-4 py-3 border-b border-danger-muted bg-danger-subtle rounded-t-md">
          <h2 className="text-sm font-semibold text-danger">Danger zone</h2>
        </div>
        <div className="px-4 py-3 flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-fg">Delete this schema</p>
            <p className="text-xs text-fg-muted">
              Moves this schema (and the records typed by it) to Recently
              Deleted — restore it any time before it's permanently purged.
            </p>
          </div>
          <Button
            variant="danger"
            size="sm"
            onClick={() => setConfirmDelete(true)}
          >
            Delete schema
          </Button>
        </div>
      </div>

      {confirmDelete &&
        (() => {
          const childCount = deleteImpact?.child_schema_count ?? 0
          const recordCount = deleteImpact?.record_count ?? 0
          const impactReady = !!deleteImpact && !deleteImpactLoading
          const highImpact =
            impactReady &&
            (childCount > 0 || recordCount > HIGH_IMPACT_RECORD_THRESHOLD)

          return (
            <ConfirmDialog
              title="Delete schema"
              body={
                <>
                  <p>
                    Delete schema '{schema.name}'?{' '}
                    {impactReady
                      ? describeDeleteImpact(childCount, recordCount)
                      : 'Checking what depends on this schema…'}
                  </p>
                </>
              }
              confirmLabel={
                impactReady
                  ? recordCount > 0
                    ? `Delete schema and ${recordCount.toLocaleString()} record${recordCount === 1 ? '' : 's'}`
                    : 'Delete schema'
                  : 'Checking…'
              }
              variant="danger"
              confirmDisabled={!impactReady}
              typedConfirmationValue={highImpact ? schema.name : undefined}
              warning={
                deleteSchema.error
                  ? errorMessage(deleteSchema.error)
                  : undefined
              }
              isPending={deleteSchema.isPending}
              onConfirm={() =>
                deleteSchema.mutate(
                  {
                    name: schema.name,
                    undo: () => schemasApi.restore(schema.name),
                  },
                  { onSuccess: () => navigate('/schemas') },
                )
              }
              onClose={() => setConfirmDelete(false)}
            />
          )
        })()}
    </Page>
  )
}
