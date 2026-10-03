import { useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router'
import { errorMessage } from '../lib/errors'
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
  TabNav,
  TabPanel,
  useTabParam,
} from '../components/ui'
import { displayLabel, nameError } from '../utils/naming'
import { Upload } from '../components/ui/icons'
import { SchemaFieldsSection } from '../components/schemas/SchemaFieldsSection'
import { NamingSection } from '../components/schemas/NamingSection'
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

const TABS = [
  { id: 'fields', label: 'Fields' },
  { id: 'naming', label: 'Naming' },
  { id: 'automations', label: 'Automations' },
  { id: 'history', label: 'History' },
] as const
type TabId = (typeof TABS)[number]['id']

export default function SchemaDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [editing, setEditing] = useState(false)
  const [tab, setTab] = useTabParam<TabId>(TABS, 'fields')
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
      meta={
        <p className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span
            className="font-mono text-xs text-fg-subtle"
            title="Schema name — what workflows and CSV headers reference"
          >
            {schema.name}
          </span>
          {parentSchema && (
            <span className="text-xs">
              inherits{' '}
              <Link
                to={`/schemas/${parentSchema.id}`}
                className="text-accent hover:underline"
              >
                {parentSchema.name}
              </Link>
            </span>
          )}
          {schema.description && <span>{schema.description}</span>}
        </p>
      }
      secondaryActions={[
        {
          label: 'Delete schema…',
          variant: 'danger',
          onClick: () => setConfirmDelete(true),
        },
      ]}
      action={
        !editing && (
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="primary"
              to={`/schemas/${schema.id}/import`}
            >
              <Upload size={14} /> Import data
            </Button>
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

      <TabNav label="Schema" tabs={[...TABS]} value={tab} onChange={setTab} />
      <TabPanel id="fields" value={tab}>
        <SchemaFieldsSection schema={schema} allSchemas={allSchemas} />
      </TabPanel>

      <TabPanel id="naming" value={tab}>
        <NamingSection schema={schema} allSchemas={allSchemas} />
      </TabPanel>

      <TabPanel id="automations" value={tab}>
        <WorkflowsPanel
          schemaName={schema.name}
          onRun={(wf) => setRunTarget(wf)}
          onView={(wf) => setSummaryTarget(wf)}
        />
      </TabPanel>

      <TabPanel id="history" value={tab}>
        <AuditTrail
          queryKey={['schemas', schema.name, 'audit']}
          fetchPage={(offset, limit, table) =>
            schemasApi.getAudit(schema.name, offset, limit, table)
          }
          describeEntry={describeSchemaAuditEntry}
          emptyMessage="No changes yet."
        />
      </TabPanel>

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
