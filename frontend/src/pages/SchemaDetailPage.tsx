import { useState, useCallback } from 'react'
import { useParams, useNavigate, Link } from 'react-router'
import { errorMessage } from '../lib/errors'
import {
  useSchema,
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
  Table,
  Thead,
  Th,
  Tbody,
  Tr,
  Td,
  DetailSkeleton,
  TableSkeleton,
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

  // Fetch by UUID — name changes don't affect the URL
  const { data: schema, isLoading, error } = useSchema(id!)
  const { data: allSchemas } = useSchemas()
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
    ;[newOrder[index], newOrder[targetIndex]] = [
      newOrder[targetIndex],
      newOrder[index],
    ]
    reorderFields.mutate(newOrder.map((f) => f.id))
  }

  const breadcrumbs = [{ label: 'Schemas', to: '/schemas' }]

  if (isLoading)
    return (
      <Page
        breadcrumbs={breadcrumbs}
        loading={
          <>
            <DetailSkeleton metadataRows={0} sections={0} />
            <TableSkeleton
              columns={['w-8', 'w-32', 'w-20', 'w-16', 'w-24']}
              rows={6}
            />
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
          <Button size="sm" onClick={() => setEditing(true)}>
            Edit
          </Button>
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

        <Table>
          <Thead>
            <tr>
              <Th className="w-8" />
              <Th>Name</Th>
              <Th>Type</Th>
              <Th>Required</Th>
              <Th className="w-24" />
            </tr>
          </Thead>
          <Tbody>
            {schema.fields.length === 0 && !addingField && (
              <Tr>
                <td
                  colSpan={5}
                  className="px-4 py-3 text-sm text-fg-muted italic"
                >
                  No fields yet.
                </td>
              </Tr>
            )}
            {schema.fields.map((field, index) =>
              editingField === field.name ? (
                <tr key={field.id} className="bg-canvas">
                  <td colSpan={5} className="p-0">
                    <FieldForm
                      mode="edit"
                      field={field}
                      schemaName={schema.name}
                      onDone={() => setEditingField(null)}
                    />
                  </td>
                </tr>
              ) : (
                <tr
                  key={field.id}
                  draggable
                  onDragStart={() => handleDragStart(index)}
                  onDragOver={(e: React.DragEvent) => handleDragOver(e, index)}
                  onDrop={() => handleDrop(index)}
                  onDragEnd={handleDragEnd}
                  className={`bg-canvas transition-colors ${
                    dragOverIndex === index && dragSrcIndex !== index
                      ? 'bg-accent-subtle outline outline-2 outline-accent'
                      : dragSrcIndex === index
                        ? 'opacity-50'
                        : ''
                  }`}
                >
                  {/* Drag handle + reorder buttons */}
                  <Td className="w-8 cursor-grab text-border hover:text-fg-muted select-none">
                    <div className="flex flex-col items-center gap-1">
                      <IconButton
                        icon={ChevronUp}
                        aria-label="Move field up"
                        variant="subtle"
                        disabled={index === 0 || reorderFields.isPending}
                        onClick={() => moveField(index, 'up')}
                      />
                      <span title="Drag to reorder">
                        <GripVertical size={12} />
                      </span>
                      <IconButton
                        icon={ChevronDown}
                        aria-label="Move field down"
                        variant="subtle"
                        disabled={
                          index === schema.fields.length - 1 ||
                          reorderFields.isPending
                        }
                        onClick={() => moveField(index, 'down')}
                      />
                    </div>
                  </Td>
                  <Td>
                    <span className="flex flex-col gap-1">
                      <span className="flex items-center gap-2">
                        <span className="text-sm font-medium">
                          {displayLabel(field.name, field.label)}
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
                      </span>
                      <span
                        className="font-mono text-xs text-fg-subtle"
                        title="Field name — what workflows and CSV headers reference"
                      >
                        {field.name}
                      </span>
                      {field.default !== null &&
                        field.default !== undefined && (
                          <span className="text-xs text-attention">
                            default: {String(field.default)}
                          </span>
                        )}
                    </span>
                  </Td>
                  <Td>
                    <div className="flex flex-col gap-1">
                      <div className="flex items-center gap-2">
                        <Badge variant="accent">{field.type}</Badge>
                        {field.type === 'reference' &&
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
                      </div>
                      <RestrictionsSummary
                        restrictions={field.restrictions}
                        type={field.type}
                      />
                    </div>
                  </Td>
                  <Td>
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
                  </Td>
                  <Td>
                    <span className="flex items-center gap-2">
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
                              aria-label="Move earlier in display order"
                              variant="subtle"
                              className="!text-attention hover:!text-attention-emphasis"
                              disabled={
                                schema.display_fields.indexOf(field.name) ===
                                  0 || updateSchema.isPending
                              }
                              onClick={() => moveDisplayField(field.name, 'up')}
                            />
                            <IconButton
                              icon={ChevronDown}
                              aria-label="Move later in display order"
                              variant="subtle"
                              className="!text-attention hover:!text-attention-emphasis"
                              disabled={
                                schema.display_fields.indexOf(field.name) ===
                                  schema.display_fields.length - 1 ||
                                updateSchema.isPending
                              }
                              onClick={() =>
                                moveDisplayField(field.name, 'down')
                              }
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
                    </span>
                  </Td>
                </tr>
              ),
            )}
          </Tbody>
          {addingField && (
            <tfoot>
              <tr>
                <td colSpan={5} className="p-0">
                  <FieldForm
                    mode="create"
                    schemaName={schema.name}
                    onDone={() => setAddingField(false)}
                  />
                </td>
              </tr>
            </tfoot>
          )}
        </Table>
      </div>

      {/* Danger zone */}
      <div className="border border-danger-muted rounded-md">
        <div className="px-4 py-3 border-b border-danger-muted bg-danger-subtle rounded-t-md">
          <h2 className="text-sm font-semibold text-danger">Danger zone</h2>
        </div>
        <div className="px-4 py-3 flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-fg">Delete this schema</p>
            <p className="text-xs text-fg-muted">
              This cannot be undone. All field definitions will be removed.
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

      {confirmDelete && (
        <ConfirmDialog
          title="Delete schema"
          body={`Delete schema '${schema.name}'? This cannot be undone. All field definitions will be removed.`}
          confirmLabel="Delete"
          variant="danger"
          warning={
            deleteSchema.error ? errorMessage(deleteSchema.error) : undefined
          }
          isPending={deleteSchema.isPending}
          onConfirm={() =>
            deleteSchema.mutate(schema.name, {
              onSuccess: () => navigate('/schemas'),
            })
          }
          onClose={() => setConfirmDelete(false)}
        />
      )}
    </Page>
  )
}
