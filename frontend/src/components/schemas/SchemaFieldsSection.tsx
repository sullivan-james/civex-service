import { useCallback, useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { errorMessage } from '../../lib/errors'
import type { Field, FieldKind, Schema } from '../../api/schemas'
import { useDeleteField, useReorderFields } from '../../hooks/useSchemas'
import { useFieldTypes } from '../../hooks/useFieldTypes'
import {
  Button,
  ConfirmDialog,
  IconButton,
  ListButton,
  SortableList,
} from '../ui'
import { displayLabel } from '../../utils/naming'
import { summarise } from '../../utils/restrictions'
import { fieldsWithInherited } from '../../utils/schemaFields'
import { X, ArrowRight } from '../ui/icons'
import { FieldForm } from './FieldForm'
import { FieldKindPicker } from './FieldKindPicker'

/** One panel of the field inspector. Today there is one (the rules); a
 * field's views (how its values are displayed, such as a spectrogram for
 * audio) are meant to be added here as another section, with their own
 * settings kept apart from the validation rules. */
interface InspectorSection {
  id: string
  label: string
  render: () => ReactNode
}

/** The schema page's Fields tab: a list of fields on the left, and for the
 * selected one an inspector on the right to change its rules. Also owns
 * reordering (drag and keyboard) and removal. */
export function SchemaFieldsSection({
  schema,
  allSchemas,
}: {
  schema: Schema
  allSchemas: Schema[] | undefined
}) {
  const [selected, setSelected] = useState<string | null>(
    schema.fields[0]?.name ?? null,
  )
  const [adding, setAdding] = useState(false)
  const [newKind, setNewKind] = useState<FieldKind | null>(null)
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

  const field = schema.fields.find((f) => f.name === selected) ?? null
  const fieldInfo = fieldsWithInherited(schema, allSchemas)

  /** Run a navigation, asking first if the open form has unsaved edits. */
  function navigate(action: () => void) {
    if (dirty) setPendingNav(() => action)
    else action()
  }
  const select = (name: string) =>
    navigate(() => {
      setSelected(name)
      setAdding(false)
      setNewKind(null)
    })
  const startAdding = () =>
    navigate(() => {
      setAdding(true)
      setNewKind(null)
      setDirty(false)
    })
  const onDirtyChange = useCallback((d: boolean) => setDirty(d), [])

  const sectionsFor = (f: Field): InspectorSection[] => [
    {
      id: 'rules',
      label: 'Rules',
      render: () => (
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
          }}
        />
      ),
    },
  ]

  function inspector() {
    if (adding || schema.fields.length === 0) {
      if (!newKind)
        return (
          <FieldKindPicker
            onPick={setNewKind}
            onCancel={schema.fields.length ? () => setAdding(false) : undefined}
          />
        )
      return (
        <div className="space-y-4">
          <h3 className="text-sm font-semibold text-fg">New field</h3>
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
              if (savedName) setSelected(savedName)
            }}
          />
        </div>
      )
    }
    if (!field)
      return (
        <p className="py-8 text-center text-sm text-fg-muted">
          Select a field to edit it.
        </p>
      )
    const sections = sectionsFor(field)
    const index = schema.fields.findIndex((f) => f.name === field.name)
    const refTarget =
      (field.type === 'reference' || field.type === 'reference_list') &&
      typeof field.restrictions?.schema === 'string'
        ? allSchemas?.find((s) => s.name === field.restrictions.schema)
        : undefined
    return (
      <div className="space-y-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="text-base font-semibold text-fg">
              {displayLabel(field.name, field.label)}
            </h3>
            <p className="flex flex-wrap items-center gap-x-2 text-xs text-fg-subtle">
              <span
                className="font-mono"
                title="Field name — what workflows and CSV headers reference"
              >
                {field.name}
              </span>
              <span>· {typeLabel(field.type)}</span>
              {refTarget && (
                <Link
                  to={`/schemas/${refTarget.id}`}
                  className="inline-flex items-center gap-1 text-accent hover:underline"
                >
                  <ArrowRight size={12} /> {refTarget.name}
                </Link>
              )}
            </p>
          </div>
          <div className="flex items-center gap-1">
            <IconButton
              icon={X}
              aria-label="Remove field"
              variant="danger"
              onClick={() => setConfirmDeleteField(field.name)}
            />
          </div>
        </div>
        {sections.map((section) => (
          <div key={section.id}>
            {sections.length > 1 && (
              <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-fg-muted">
                {section.label}
              </h4>
            )}
            {section.render()}
          </div>
        ))}
        <p className="sr-only">
          Position {index + 1} of {schema.fields.length}
        </p>
      </div>
    )
  }

  return (
    <>
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <p className="text-sm text-fg-muted">
            {schema.fields.length}{' '}
            {schema.fields.length === 1 ? 'field' : 'fields'}
          </p>
          {!adding && (
            <Button size="sm" onClick={startAdding}>
              + Add field
            </Button>
          )}
        </div>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-[minmax(15rem,20rem)_minmax(0,1fr)]">
          <div className="self-start overflow-hidden rounded-md border border-border bg-canvas">
            {schema.fields.length === 0 ? (
              <p className="px-3 py-4 text-sm text-fg-muted">No fields yet</p>
            ) : (
              <SortableList
                label="Fields"
                items={schema.fields}
                getKey={(f) => f.id}
                getLabel={(f) => displayLabel(f.name, f.label)}
                disabled={reorderFields.isPending}
                moveButtons={(f) => f.name === selected && !adding}
                onReorder={(next) =>
                  reorderFields.mutate(next.map((f) => f.id))
                }
                rowClassName={(f) =>
                  f.name === selected && !adding ? 'bg-accent-subtle' : ''
                }
                renderItem={(f) => {
                  const active = f.name === selected && !adding
                  const summary = summarise(f.restrictions, f.type)
                  return (
                    <ListButton
                      aria-current={active ? 'true' : undefined}
                      active={active}
                      onClick={() => select(f.name)}
                      className="px-1"
                    >
                      <span className="flex items-baseline gap-1.5">
                        <span className="truncate font-medium text-fg">
                          {displayLabel(f.name, f.label)}
                        </span>
                        {f.required && (
                          <span
                            className="text-attention"
                            aria-label="required"
                          >
                            *
                          </span>
                        )}
                      </span>
                      <span className="block truncate font-mono text-xs text-fg-subtle">
                        {f.name} · {typeLabel(f.type)}
                      </span>
                      {summary && (
                        <span className="block truncate text-xs text-fg-muted">
                          {summary}
                        </span>
                      )}
                    </ListButton>
                  )
                }}
              />
            )}
          </div>
          <div className="min-w-0 rounded-md border border-border bg-canvas p-4">
            {inspector()}
          </div>
        </div>
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
          body={`Remove field '${confirmDeleteField}'? This cannot be undone.`}
          confirmLabel="Remove"
          variant="danger"
          warning={
            deleteField.error ? errorMessage(deleteField.error) : undefined
          }
          isPending={deleteField.isPending}
          onConfirm={() =>
            deleteField.mutate(confirmDeleteField, {
              onSuccess: () => {
                setConfirmDeleteField(null)
                if (selected === confirmDeleteField) setSelected(null)
              },
            })
          }
          onClose={() => setConfirmDeleteField(null)}
        />
      )}
    </>
  )
}
