import { useCallback, useState } from 'react'
import { Link } from 'react-router'
import { errorMessage } from '../../lib/errors'
import type { Field, FieldKind, Schema } from '../../api/schemas'
import { useDeleteField, useReorderFields } from '../../hooks/useSchemas'
import { useFieldTypes } from '../../hooks/useFieldTypes'
import { usePermissions } from '../../hooks/useMe'
import {
  Badge,
  Button,
  ConfirmDialog,
  EmptyState,
  InfoTip,
  ListButton,
  SortableList,
} from '../ui'
import { displayLabel } from '../../utils/naming'
import { summarise } from '../../utils/restrictions'
import { fieldsWithInherited } from '../../utils/schemaFields'
import { ArrowRight, ChevronDown, ChevronUp, Plus } from '../ui/icons'
import { FieldForm } from './FieldForm'
import { FieldKindPicker } from './FieldKindPicker'

/** The schema page's Fields tab: one column of the schema's fields, each a
 * wide row that opens in place to be changed, and one way to add a field at
 * the end. Also owns reordering (drag, arrows, keyboard) and removal. */
export function SchemaFieldsSection({
  schema,
  allSchemas,
}: {
  schema: Schema
  allSchemas: Schema[] | undefined
}) {
  // What is open: one field's editor, or the add-field card at the end.
  const [open, setOpen] = useState<string | null>(null)
  const [adding, setAdding] = useState(schema.fields.length === 0)
  const [newKind, setNewKind] = useState<FieldKind | null>(null)
  const { can, why } = usePermissions()
  const cannotChange = can('change_structure')
    ? undefined
    : why('change_structure')
  const [dirty, setDirty] = useState(false)
  const [formKey, setFormKey] = useState(0)
  const [pendingNav, setPendingNav] = useState<(() => void) | null>(null)
  const [confirmDeleteField, setConfirmDeleteField] = useState<string | null>(
    null,
  )
  const deleteField = useDeleteField(schema.name)
  const reorderFields = useReorderFields(schema.name)
  const descriptors = useFieldTypes()
  const typeLabel = (t: string) =>
    descriptors?.types.find((d) => d.type === t)?.label ?? t
  const fieldInfo = fieldsWithInherited(schema, allSchemas)

  /** Run a navigation, asking first if the open form has unsaved edits. */
  function navigate(action: () => void) {
    if (dirty) setPendingNav(() => action)
    else action()
  }
  const toggle = (name: string) =>
    navigate(() => {
      setOpen((current) => (current === name ? null : name))
      setAdding(false)
      setNewKind(null)
      setDirty(false)
    })
  const startAdding = () =>
    navigate(() => {
      setOpen(null)
      setAdding(true)
      setNewKind(null)
      setDirty(false)
    })
  const stopAdding = () =>
    navigate(() => {
      setAdding(false)
      setNewKind(null)
      setDirty(false)
    })
  const onDirtyChange = useCallback((d: boolean) => setDirty(d), [])

  const refTarget = (field: Field) =>
    (field.type === 'reference' || field.type === 'reference_list') &&
    typeof field.restrictions?.schema === 'string'
      ? allSchemas?.find((s) => s.name === field.restrictions.schema)
      : undefined

  const addCard = (
    <section
      aria-label="New field"
      className="rounded-lg border border-accent bg-canvas p-5"
    >
      {!newKind ? (
        <FieldKindPicker
          onPick={setNewKind}
          onCancel={schema.fields.length ? stopAdding : undefined}
        />
      ) : (
        <div className="space-y-5">
          <h3 className="text-base font-semibold text-fg">
            New {newKind.label.toLowerCase()} field
          </h3>
          <FieldForm
            key={newKind.key}
            mode="create"
            kind={newKind}
            schemaName={schema.name}
            schemas={allSchemas}
            fields={fieldInfo}
            onChangeKind={() => setNewKind(null)}
            onDirtyChange={onDirtyChange}
            onDone={(savedName) => {
              setDirty(false)
              setNewKind(null)
              setAdding(false)
              if (savedName) setOpen(null)
            }}
          />
        </div>
      )}
    </section>
  )

  return (
    <>
      <div className="space-y-4">
        {schema.fields.length === 0 ? (
          !adding && (
            <EmptyState
              title="No fields yet"
              action={
                <Button
                  variant="primary"
                  onClick={startAdding}
                  disabled={!!cannotChange}
                  title={cannotChange}
                >
                  <Plus size={16} /> Add field
                </Button>
              }
            />
          )
        ) : (
          <div className="overflow-hidden rounded-lg border border-border bg-canvas">
            <SortableList
              label="Fields"
              items={schema.fields}
              getKey={(f) => f.id}
              getLabel={(f) => displayLabel(f.name, f.label)}
              disabled={reorderFields.isPending || !!cannotChange}
              moveButtons={(f) => f.name === open}
              onReorder={(next) => reorderFields.mutate(next.map((f) => f.id))}
              rowClassName={(f) =>
                f.name === open ? 'bg-canvas-subtle' : 'hover:bg-canvas-subtle'
              }
              renderItem={(f) => {
                const isOpen = f.name === open
                const summary = summarise(f.restrictions, f.type)
                const target = refTarget(f)
                return (
                  <div>
                    <div className="flex items-center">
                      <ListButton
                        aria-expanded={isOpen}
                        onClick={() => toggle(f.name)}
                        className="flex min-h-16 flex-1 items-center gap-4 px-3 py-3 text-base"
                      >
                        <span className="min-w-0 flex-1">
                          <span className="flex flex-wrap items-baseline gap-x-2">
                            <span className="font-medium text-fg">
                              {displayLabel(f.name, f.label)}
                            </span>
                            <span
                              className="font-mono text-xs text-fg-subtle"
                              title="Key — what workflows and CSV headers use"
                            >
                              {f.name}
                            </span>
                          </span>
                          <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-fg-muted">
                            <Badge>{typeLabel(f.type)}</Badge>
                            {f.required && (
                              <Badge variant="accent">Required</Badge>
                            )}
                            {summary && <span>{summary}</span>}
                            {target && (
                              <span>
                                → {displayLabel(target.name, target.label)}
                              </span>
                            )}
                          </span>
                        </span>
                        <span className="shrink-0 text-fg-subtle">
                          {isOpen ? (
                            <ChevronUp size={18} aria-hidden="true" />
                          ) : (
                            <ChevronDown size={18} aria-hidden="true" />
                          )}
                        </span>
                      </ListButton>
                      {target && (
                        <Link
                          to={`/schemas/${target.id}`}
                          className="mr-3 inline-flex min-h-9 shrink-0 items-center gap-1 rounded-md px-2 text-sm text-accent hover:underline"
                          aria-label={`Open ${displayLabel(target.name, target.label)}`}
                        >
                          <ArrowRight size={14} aria-hidden="true" />
                        </Link>
                      )}
                    </div>
                    {isOpen && (
                      <div className="border-t border-border px-5 py-5">
                        <h3 className="sr-only">
                          {displayLabel(f.name, f.label)}
                        </h3>
                        <FieldForm
                          key={`${f.id}-${formKey}`}
                          mode="edit"
                          field={f}
                          schemaName={schema.name}
                          schemas={allSchemas}
                          fields={fieldInfo}
                          onDirtyChange={onDirtyChange}
                          onDone={() => {
                            setDirty(false)
                            setFormKey((k) => k + 1)
                            setOpen(null)
                          }}
                          onRemove={
                            cannotChange
                              ? undefined
                              : () => setConfirmDeleteField(f.name)
                          }
                        />
                      </div>
                    )}
                  </div>
                )
              }}
            />
          </div>
        )}

        {adding
          ? addCard
          : schema.fields.length > 0 && (
              <div className="flex items-center justify-between gap-3">
                <p className="flex items-center gap-1 text-sm text-fg-muted">
                  {schema.fields.length}{' '}
                  {schema.fields.length === 1 ? 'field' : 'fields'}
                  <InfoTip>
                    Press a row to change its rules. Drag a row to reorder, or
                    open one and use its arrows.
                  </InfoTip>
                </p>
                <Button
                  variant="primary"
                  onClick={startAdding}
                  disabled={!!cannotChange}
                  title={cannotChange}
                >
                  <Plus size={16} /> Add field
                </Button>
              </div>
            )}
      </div>

      {pendingNav && (
        <ConfirmDialog
          title="Discard unsaved changes?"
          body="This field has changes that haven't been saved."
          confirmLabel="Discard changes"
          variant="danger"
          onConfirm={() => {
            const go = pendingNav
            setPendingNav(null)
            setDirty(false)
            setFormKey((k) => k + 1)
            go()
          }}
          onClose={() => setPendingNav(null)}
        />
      )}

      {confirmDeleteField && (
        <ConfirmDialog
          title="Remove field"
          body={`Remove the field '${confirmDeleteField}'? Records keep their values for it, and it can be restored.`}
          confirmLabel="Remove field"
          variant="danger"
          warning={
            deleteField.error ? errorMessage(deleteField.error) : undefined
          }
          onConfirm={() =>
            deleteField.mutate(confirmDeleteField, {
              onSuccess: () => {
                setConfirmDeleteField(null)
                setOpen(null)
              },
            })
          }
          onClose={() => setConfirmDeleteField(null)}
        />
      )}
    </>
  )
}
