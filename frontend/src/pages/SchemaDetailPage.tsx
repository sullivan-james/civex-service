import { useState, useCallback } from 'react'
import { useParams, useNavigate, Link } from 'react-router'
import { errorMessage } from '../lib/errors'
import { schemasApi } from '../api/schemas'
import {
  useSchema,
  useSchemaDeleteImpact,
  useUpdateSchema,
  useUpdateField,
  useDeleteSchema,
  useDeleteField,
  useSchemas,
  useReorderFields,
} from '../hooks/useSchemas'
import {
  Button,
  IconButton,
  Badge,
  DetailSkeleton,
  Skeleton,
  ErrorState,
  Field,
  Input,
  ConfirmDialog,
  Page,
  FormGrid,
  NameLabelFields,
} from '../components/ui'
import { displayLabel, nameError } from '../utils/naming'
import {
  Star,
  Pencil,
  X,
  ChevronUp,
  ChevronDown,
  GripVertical,
  ArrowRight,
} from '../components/ui/icons'
import { FieldForm } from '../components/schemas/FieldForm'
import { RestrictionsSummary } from '../components/schemas/RestrictionsSummary'
import { AuditTrail } from '../components/audit/AuditTrail'
import { describeAuditEntry as describeSchemaAuditEntry } from '../utils/schemaAudit'

// Above this many records, or with any child schema, deleting is treated as
// high-impact: the confirm button stays disabled until the user types the
// schema name, instead of a single click.
const HIGH_IMPACT_RECORD_THRESHOLD = 25

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
  const [addingField, setAddingField] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [dragSrcIndex, setDragSrcIndex] = useState<number | null>(null)
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null)
  const [announcement, setAnnouncement] = useState('')

  // Fetch by UUID — name changes don't affect the URL
  const { data: schema, isLoading, error } = useSchema(id!)
  const { data: allSchemas } = useSchemas()
  const { data: deleteImpact, isLoading: deleteImpactLoading } =
    useSchemaDeleteImpact(schema?.name ?? '', confirmDelete)
  const updateField = useUpdateField(schema?.name ?? '')
  const deleteField = useDeleteField(schema?.name ?? '')
  const deleteSchema = useDeleteSchema()
  const updateSchema = useUpdateSchema(schema?.name ?? '')
  const reorderFields = useReorderFields(schema?.name ?? '')
  const [editingField, setEditingField] = useState<string | null>(null)
  const [confirmDeleteField, setConfirmDeleteField] = useState<string | null>(
    null,
  )

  function toggleDisplayField(fieldName: string) {
    if (!schema) return
    const current = schema.display_fields
    const next = current.includes(fieldName)
      ? current.filter((n) => n !== fieldName)
      : [...current, fieldName]
    updateSchema.mutate({ display_fields: next })
  }

  function moveDisplayField(fieldName: string, direction: 'up' | 'down') {
    if (!schema) return
    const current = [...schema.display_fields]
    const index = current.indexOf(fieldName)
    const targetIndex = direction === 'up' ? index - 1 : index + 1
    if (index === -1 || targetIndex < 0 || targetIndex >= current.length) return
    ;[current[index], current[targetIndex]] = [
      current[targetIndex],
      current[index],
    ]
    updateSchema.mutate({ display_fields: current })
    const field = schema.fields.find((f) => f.name === fieldName)
    const label = field ? displayLabel(field.name, field.label) : fieldName
    setAnnouncement(
      `${label} moved to position ${targetIndex + 1} of ${current.length} in display order.`,
    )
  }

  const handleDragStart = useCallback((index: number) => {
    setDragSrcIndex(index)
  }, [])

  const handleDragOver = useCallback((e: React.DragEvent, index: number) => {
    e.preventDefault()
    setDragOverIndex(index)
  }, [])

  const handleDrop = useCallback(
    (index: number) => {
      if (dragSrcIndex === null || dragSrcIndex === index || !schema) {
        setDragSrcIndex(null)
        setDragOverIndex(null)
        return
      }
      const newOrder = [...schema.fields]
      const [moved] = newOrder.splice(dragSrcIndex, 1)
      newOrder.splice(index, 0, moved)
      reorderFields.mutate(newOrder.map((f) => f.id))
      setAnnouncement(
        `${displayLabel(moved.name, moved.label)} moved to position ${index + 1} of ${newOrder.length}.`,
      )
      setDragSrcIndex(null)
      setDragOverIndex(null)
    },
    [dragSrcIndex, schema, reorderFields],
  )

  const handleDragEnd = useCallback(() => {
    setDragSrcIndex(null)
    setDragOverIndex(null)
  }, [])

  function moveField(index: number, direction: 'up' | 'down') {
    if (!schema) return
    const newOrder = [...schema.fields]
    const targetIndex = direction === 'up' ? index - 1 : index + 1
    if (targetIndex < 0 || targetIndex >= newOrder.length) return
    const moved = newOrder[index]
    ;[newOrder[index], newOrder[targetIndex]] = [
      newOrder[targetIndex],
      newOrder[index],
    ]
    reorderFields.mutate(newOrder.map((f) => f.id))
    setAnnouncement(
      `${displayLabel(moved.name, moved.label)} moved to position ${targetIndex + 1} of ${newOrder.length}.`,
    )
  }

  function handleRowKeyDown(
    e: React.KeyboardEvent<HTMLDivElement>,
    index: number,
  ) {
    if (!(e.altKey || e.metaKey)) return
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      moveField(index, 'up')
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      moveField(index, 'down')
    }
  }

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
            <Link to={`/schemas/${schema.id}/views`}>
              <Button size="sm">Views</Button>
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

      {/* Fields */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-base font-semibold text-fg">
            Fields
            <span className="ml-2 text-sm font-normal text-fg-muted">
              {schema.fields.length} own
            </span>
          </h2>
          {!addingField && (
            <Button size="sm" onClick={() => setAddingField(true)}>
              + Add field
            </Button>
          )}
        </div>
        <p className="text-xs text-fg-subtle mb-2">
          Click <Star size={11} className="inline align-text-top" /> to mark a
          field as a display field — its value is used to name records of this
          type wherever they're listed.
        </p>
        <p className="text-xs text-fg-subtle mb-2">
          Focus a field row and press Alt/Cmd + Arrow Up/Down to reorder it with
          the keyboard.
        </p>
        <div role="status" aria-live="polite" className="sr-only">
          {announcement}
        </div>

        <div className="flex flex-col gap-2">
          {schema.fields.length === 0 && !addingField && (
            <p className="text-sm text-fg-muted italic border border-dashed border-border rounded-md px-4 py-6 text-center">
              No fields yet.
            </p>
          )}
          {schema.fields.map((field, index) =>
            editingField === field.name ? (
              <div
                key={field.id}
                className="border border-accent-muted rounded-md overflow-hidden"
              >
                <FieldForm
                  mode="edit"
                  field={field}
                  schemaName={schema.name}
                  onDone={() => setEditingField(null)}
                />
              </div>
            ) : (
              <div
                key={field.id}
                tabIndex={0}
                onKeyDown={(e) => handleRowKeyDown(e, index)}
                onDragOver={(e: React.DragEvent) => handleDragOver(e, index)}
                onDrop={() => handleDrop(index)}
                className={`flex items-start gap-2 rounded-md border p-3 bg-canvas transition-colors focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-accent ${
                  dragOverIndex === index && dragSrcIndex !== index
                    ? 'bg-accent-subtle outline outline-2 outline-accent border-accent'
                    : dragSrcIndex === index
                      ? 'opacity-50 border-border'
                      : 'border-border'
                }`}
              >
                {/* Drag handle + reorder buttons */}
                <div className="flex flex-col items-center gap-1 shrink-0 pt-0.5 text-border hover:text-fg-muted select-none">
                  <IconButton
                    icon={ChevronUp}
                    aria-label={`Move ${displayLabel(field.name, field.label)} up`}
                    variant="subtle"
                    disabled={index === 0 || reorderFields.isPending}
                    onClick={() => moveField(index, 'up')}
                  />
                  <span
                    draggable
                    onDragStart={() => handleDragStart(index)}
                    onDragEnd={handleDragEnd}
                    title="Drag to reorder"
                    aria-hidden="true"
                    className="cursor-grab active:cursor-grabbing"
                  >
                    <GripVertical size={12} />
                  </span>
                  <IconButton
                    icon={ChevronDown}
                    aria-label={`Move ${displayLabel(field.name, field.label)} down`}
                    variant="subtle"
                    disabled={
                      index === schema.fields.length - 1 ||
                      reorderFields.isPending
                    }
                    onClick={() => moveField(index, 'down')}
                  />
                </div>

                <div className="flex-1 min-w-0 flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                  {/* Identity + type/restrictions */}
                  <div className="flex flex-col gap-1 min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium">
                        {displayLabel(field.name, field.label)}
                      </span>
                      <span
                        className="font-mono text-xs text-fg-subtle"
                        title="Field name — what workflows and CSV headers reference"
                      >
                        {field.name}
                      </span>
                      {schema.display_fields.includes(field.name) && (
                        <span
                          className="text-xs font-medium px-2 py-1 rounded-full bg-attention-subtle text-attention border border-attention-muted"
                          title="Display field — included in the record's natural name"
                        >
                          display
                          {schema.display_fields.length > 1 &&
                            ` #${schema.display_fields.indexOf(field.name) + 1}`}
                        </span>
                      )}
                    </div>
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <Badge variant="accent">{field.type}</Badge>
                      {(field.type === 'reference' ||
                        field.type === 'reference_list') &&
                        !!field.restrictions?.schema && (
                          <span className="inline-flex items-center gap-1 text-xs text-fg-muted">
                            <ArrowRight size={12} />
                            <Link
                              to={`/schemas/${allSchemas?.find((s) => s.name === String(field.restrictions.schema))?.id ?? String(field.restrictions.schema)}`}
                              className="text-accent hover:underline"
                            >
                              {String(field.restrictions.schema)}
                            </Link>
                          </span>
                        )}
                      <button
                        onClick={() =>
                          updateField.mutate({
                            fieldName: field.name,
                            required: !field.required,
                          })
                        }
                        className={`text-xs font-medium px-2 py-1 rounded-full border cursor-pointer transition-colors ${
                          field.required
                            ? 'bg-success-subtle text-success border-success-muted hover:bg-success-subtle-hover'
                            : 'bg-canvas-subtle text-fg-muted border-border hover:bg-canvas-inset'
                        }`}
                      >
                        {field.required ? 'Required' : 'Optional'}
                      </button>
                      <RestrictionsSummary
                        restrictions={field.restrictions}
                        type={field.type}
                      />
                      {field.default !== null &&
                        field.default !== undefined && (
                          <span className="text-xs text-attention">
                            default: {String(field.default)}
                          </span>
                        )}
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-1 shrink-0">
                    <IconButton
                      icon={Star}
                      aria-label={
                        schema.display_fields.includes(field.name)
                          ? 'Remove from display fields'
                          : 'Add to display fields'
                      }
                      variant="subtle"
                      className={
                        schema.display_fields.includes(field.name)
                          ? '!text-attention hover:!text-attention-emphasis'
                          : ''
                      }
                      iconProps={{
                        fill: schema.display_fields.includes(field.name)
                          ? 'currentColor'
                          : 'none',
                      }}
                      onClick={() => toggleDisplayField(field.name)}
                    />
                    {schema.display_fields.length > 1 &&
                      schema.display_fields.includes(field.name) && (
                        <span className="flex flex-col items-center gap-1">
                          <IconButton
                            icon={ChevronUp}
                            aria-label={`Move ${displayLabel(field.name, field.label)} earlier in display order`}
                            variant="subtle"
                            className="!text-attention hover:!text-attention-emphasis"
                            disabled={
                              schema.display_fields.indexOf(field.name) === 0 ||
                              updateSchema.isPending
                            }
                            onClick={() => moveDisplayField(field.name, 'up')}
                          />
                          <IconButton
                            icon={ChevronDown}
                            aria-label={`Move ${displayLabel(field.name, field.label)} later in display order`}
                            variant="subtle"
                            className="!text-attention hover:!text-attention-emphasis"
                            disabled={
                              schema.display_fields.indexOf(field.name) ===
                                schema.display_fields.length - 1 ||
                              updateSchema.isPending
                            }
                            onClick={() => moveDisplayField(field.name, 'down')}
                          />
                        </span>
                      )}
                    <IconButton
                      icon={Pencil}
                      aria-label="Edit field"
                      variant="default"
                      className="hover:!text-accent"
                      onClick={() => {
                        setConfirmDeleteField(null)
                        setEditingField(field.name)
                      }}
                    />
                    <IconButton
                      icon={X}
                      aria-label="Remove field"
                      variant="danger"
                      onClick={() => {
                        setEditingField(null)
                        setConfirmDeleteField(field.name)
                      }}
                    />
                  </div>
                </div>
              </div>
            ),
          )}
          {addingField && (
            <div className="border border-border rounded-md overflow-hidden">
              <FieldForm
                mode="create"
                schemaName={schema.name}
                onDone={() => setAddingField(false)}
              />
            </div>
          )}
        </div>
      </div>

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

      {confirmDeleteField && (
        <ConfirmDialog
          title="Remove field"
          body={`Remove field '${confirmDeleteField}'? This cannot be undone.`}
          confirmLabel="Remove"
          variant="danger"
          warning={
            deleteField.error ? errorMessage(deleteField.error) : undefined
          }
          isPending={deleteField.isPending}
          onConfirm={() =>
            deleteField.mutate(confirmDeleteField, {
              onSuccess: () => setConfirmDeleteField(null),
            })
          }
          onClose={() => setConfirmDeleteField(null)}
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
