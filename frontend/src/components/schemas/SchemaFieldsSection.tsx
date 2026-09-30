import { useState, useCallback } from 'react'
import { Link } from 'react-router'
import { errorMessage } from '../../lib/errors'
import type { Schema } from '../../api/schemas'
import {
  useUpdateSchema,
  useUpdateField,
  useDeleteField,
  useReorderFields,
} from '../../hooks/useSchemas'
import { Button, IconButton, Badge, ConfirmDialog, Section } from '../ui'
import { displayLabel } from '../../utils/naming'
import {
  Star,
  Pencil,
  X,
  ChevronUp,
  ChevronDown,
  GripVertical,
  ArrowRight,
} from '../ui/icons'
import { FieldForm } from './FieldForm'
import { RestrictionsSummary } from './RestrictionsSummary'

/** The schema page's Fields section: the ordered field list with inline
 * edit/add, drag + keyboard reordering, display-field ordering and the
 * remove-field confirmation. Owns all of that state so the page only
 * deals with the schema itself. */
export function SchemaFieldsSection({
  schema,
  allSchemas,
}: {
  schema: Schema
  allSchemas: Schema[] | undefined
}) {
  const [addingField, setAddingField] = useState(false)
  const [editingField, setEditingField] = useState<string | null>(null)
  const [confirmDeleteField, setConfirmDeleteField] = useState<string | null>(
    null,
  )
  const [dragSrcIndex, setDragSrcIndex] = useState<number | null>(null)
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null)
  const [announcement, setAnnouncement] = useState('')
  const updateField = useUpdateField(schema.name)
  const deleteField = useDeleteField(schema.name)
  const updateSchema = useUpdateSchema(schema.name)
  const reorderFields = useReorderFields(schema.name)

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

  return (
    <>
      <Section
        title="Fields"
        count={schema.fields.length}
        action={
          !addingField && (
            <Button size="sm" onClick={() => setAddingField(true)}>
              + Add field
            </Button>
          )
        }
      >
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
                    title="Drag to reorder, or focus the row and press Alt/Cmd+Arrow"
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
                          : "Add to display fields — used to name this type's records"
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
      </Section>

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
    </>
  )
}
