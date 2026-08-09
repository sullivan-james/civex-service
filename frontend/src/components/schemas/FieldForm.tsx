import { useState } from 'react'
import * as restrictions from '../../utils/restrictions'
import type { Field as SchemaField } from '../../api/schemas'
import { errorMessage } from '../../lib/errors'
import { useAddField, useUpdateField, useSchemas } from '../../hooks/useSchemas'
import { Button, Badge, Field, Input, Select, Checkbox } from '../ui'

const FIELD_TYPES = [
  'string',
  'integer',
  'float',
  'boolean',
  'date',
  'datetime',
  'file',
  'file_list',
  'reference',
  'enum',
  'url',
  'reference_list',
  'tags',
]

const NON_DEFAULT_TYPES = new Set([
  'file',
  'file_list',
  'reference',
  'reference_list',
])

type FieldFormProps =
  | { mode: 'create'; schemaName: string; onDone: () => void }
  | {
      mode: 'edit'
      schemaName: string
      field: SchemaField
      onDone: () => void
    }

export function FieldForm(props: FieldFormProps) {
  const { mode, schemaName, onDone } = props
  const editingField = props.mode === 'edit' ? props.field : undefined

  const [fieldName, setFieldName] = useState(editingField?.name ?? '')
  const [type, setType] = useState(editingField?.type ?? 'string')
  const [required, setRequired] = useState(editingField?.required ?? false)
  const [defaultVal, setDefaultVal] = useState('')

  const initialRestrictions = editingField
    ? restrictions.parse(editingField)
    : restrictions.EMPTY_RESTRICTION_STATE
  // reference
  const [refSchema, setRefSchema] = useState(initialRestrictions.refSchema)
  // integer/float
  const [minVal, setMinVal] = useState(initialRestrictions.min)
  const [maxVal, setMaxVal] = useState(initialRestrictions.max)
  // string/enum
  const [choices, setChoices] = useState(initialRestrictions.choices)
  const [maxLength, setMaxLength] = useState(initialRestrictions.maxLength)
  // file/file_list
  const [accept, setAccept] = useState(initialRestrictions.accept)
  const [maxSize, setMaxSize] = useState(initialRestrictions.maxSize)
  // date/datetime — stored as UTC ISO; display in datetime-local format
  const [minDate, setMinDate] = useState(initialRestrictions.minDate)
  const [maxDate, setMaxDate] = useState(initialRestrictions.maxDate)

  const addField = useAddField(schemaName)
  const updateField = useUpdateField(schemaName)
  const { data: allSchemas } = useSchemas()

  const canSubmit =
    !!fieldName.trim() &&
    (mode === 'edit' || type !== 'reference' || !!refSchema)
  const showDefault = mode === 'create' && !NON_DEFAULT_TYPES.has(type)

  function handleTypeChange(t: string) {
    setType(t)
    setDefaultVal('')
    setRefSchema('')
    setMinVal('')
    setMaxVal('')
    setChoices('')
    setMaxLength('')
    setAccept('')
    setMaxSize('')
    setMinDate('')
    setMaxDate('')
  }

  function handleSubmit() {
    if (!canSubmit) return
    const builtRestrictions = restrictions.build(type, {
      min: minVal,
      max: maxVal,
      choices,
      maxLength,
      accept,
      maxSize,
      minDate,
      maxDate,
      refSchema,
    })

    if (mode === 'create') {
      const body: Parameters<typeof addField.mutate>[0] = {
        name: fieldName.trim(),
        type,
        required,
        restrictions: builtRestrictions,
      }
      if (showDefault && defaultVal !== '') {
        body.default = defaultVal
      }
      addField.mutate(body, {
        onSuccess: () => {
          setFieldName('')
          handleTypeChange('string')
          setRequired(false)
          onDone()
        },
      })
    } else {
      const trimmed = fieldName.trim()
      updateField.mutate(
        {
          fieldName: editingField!.name,
          rename: trimmed !== editingField!.name ? trimmed : undefined,
          required,
          restrictions: builtRestrictions ?? {},
        },
        { onSuccess: onDone },
      )
    }
  }

  const mutation = mode === 'create' ? addField : updateField

  return (
    <div
      className={
        mode === 'create'
          ? 'border-t border-border bg-canvas-subtle px-4 py-3 flex flex-col gap-3'
          : 'bg-accent-subtle border-t border-border px-4 py-3 flex flex-col gap-3'
      }
    >
      {/* Row 1: name, type, required */}
      <div className="flex items-center gap-3 flex-wrap">
        <Input
          size="sm"
          value={fieldName}
          onChange={(e) => setFieldName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
          placeholder={mode === 'create' ? 'Field name' : undefined}
          autoFocus
          className="w-40"
        />
        {mode === 'create' ? (
          <Select
            size="sm"
            value={type}
            onChange={(e) => handleTypeChange(e.target.value)}
          >
            {FIELD_TYPES.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </Select>
        ) : (
          <Badge variant="accent">{type}</Badge>
        )}
        {mode === 'create' && type === 'reference' && (
          <Select
            size="sm"
            value={refSchema}
            onChange={(e) => setRefSchema(e.target.value)}
          >
            <option value="">— target schema —</option>
            {allSchemas
              ?.filter((s) => s.name !== schemaName)
              .map((s) => (
                <option key={s.id} value={s.name}>
                  {s.name}
                </option>
              ))}
          </Select>
        )}
        <Field label="Required" layout="inline">
          <Checkbox
            checked={required}
            onChange={(e) => setRequired(e.target.checked)}
          />
        </Field>
        <div className="flex gap-2 ml-auto">
          <Button
            variant="primary"
            size="sm"
            onClick={handleSubmit}
            disabled={mutation.isPending || !canSubmit}
          >
            {mode === 'create'
              ? mutation.isPending
                ? 'Adding…'
                : 'Add field'
              : mutation.isPending
                ? 'Saving…'
                : 'Save'}
          </Button>
          <Button size="sm" onClick={onDone}>
            Cancel
          </Button>
        </div>
      </div>

      {/* Default value */}
      {showDefault && (
        <div className="flex items-center gap-3 flex-wrap">
          <Field label="Default value">
            <Input
              size="sm"
              value={defaultVal}
              onChange={(e) => setDefaultVal(e.target.value)}
              placeholder="none"
              className="w-40"
            />
          </Field>
        </div>
      )}

      {/* Row 2: type-specific restrictions */}
      {(type === 'integer' || type === 'float') && (
        <div className="flex items-end gap-3 flex-wrap">
          <span className="text-xs text-fg-muted font-medium pb-2">
            Restrictions:
          </span>
          <Field label="Min">
            <Input
              size="sm"
              type="number"
              step={type === 'integer' ? '1' : 'any'}
              value={minVal}
              onChange={(e) => setMinVal(e.target.value)}
              placeholder="none"
              className="w-24"
            />
          </Field>
          <Field label="Max">
            <Input
              size="sm"
              type="number"
              step={type === 'integer' ? '1' : 'any'}
              value={maxVal}
              onChange={(e) => setMaxVal(e.target.value)}
              placeholder="none"
              className="w-24"
            />
          </Field>
        </div>
      )}
      {(type === 'string' || type === 'enum') && (
        <div className="flex items-end gap-3 flex-wrap">
          <span className="text-xs text-fg-muted font-medium pb-2">
            Restrictions:
          </span>
          <Field label="Choices (comma-separated)">
            <Input
              size="sm"
              value={choices}
              onChange={(e) => setChoices(e.target.value)}
              placeholder={
                mode === 'create' ? 'e.g. left,right,bilateral' : 'none'
              }
              className="w-52"
            />
          </Field>
          {type === 'string' && (
            <Field label="Max length">
              <Input
                size="sm"
                type="number"
                step="1"
                min="1"
                value={maxLength}
                onChange={(e) => setMaxLength(e.target.value)}
                placeholder="none"
                className="w-24"
              />
            </Field>
          )}
        </div>
      )}
      {(type === 'file' || type === 'file_list') && (
        <div className="flex items-end gap-3 flex-wrap">
          <span className="text-xs text-fg-muted font-medium pb-2">
            Restrictions:
          </span>
          <Field label="Accept">
            <Input
              size="sm"
              value={accept}
              onChange={(e) => setAccept(e.target.value)}
              placeholder=".csv,.txt"
              className="w-36"
            />
          </Field>
          <Field label="Max size (bytes)">
            <Input
              size="sm"
              type="number"
              step="1"
              min="1"
              value={maxSize}
              onChange={(e) => setMaxSize(e.target.value)}
              placeholder="none"
              className="w-28"
            />
          </Field>
        </div>
      )}
      {(type === 'date' || type === 'datetime') && (
        <div className="flex items-end gap-3 flex-wrap">
          <span className="text-xs text-fg-muted font-medium pb-2">
            Restrictions:
          </span>
          <Field label="Not before">
            <Input
              size="sm"
              type={type === 'date' ? 'date' : 'datetime-local'}
              value={minDate}
              onChange={(e) => setMinDate(e.target.value)}
            />
          </Field>
          <Field label="Not after">
            <Input
              size="sm"
              type={type === 'date' ? 'date' : 'datetime-local'}
              value={maxDate}
              onChange={(e) => setMaxDate(e.target.value)}
            />
          </Field>
        </div>
      )}

      {mutation.error && (
        <span className="text-xs text-danger">
          {errorMessage(mutation.error)}
        </span>
      )}
    </div>
  )
}
