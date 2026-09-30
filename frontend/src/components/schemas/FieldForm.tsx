import { useState } from 'react'
import * as restrictions from '../../utils/restrictions'
import type { Field as SchemaField } from '../../api/schemas'
import { errorMessage } from '../../lib/errors'
import { useAddField, useUpdateField, useSchemas } from '../../hooks/useSchemas'
import {
  Button,
  Badge,
  Field,
  Input,
  Select,
  TimeZoneSelect,
  Checkbox,
  FormGrid,
  FormSection,
  FormFooter,
  NameLabelFields,
  spanClassName,
} from '../ui'
import { displayLabel, nameError } from '../../utils/naming'
import { FIELD_TYPES } from '../../utils/fieldTypes'

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
  const [fieldLabel, setFieldLabel] = useState(editingField?.label ?? '')
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
  // datetime only: overrides the collection's timezone for this field
  const [timezone, setTimezone] = useState(initialRestrictions.timezone)

  const addField = useAddField(schemaName)
  const updateField = useUpdateField(schemaName)
  const { data: allSchemas } = useSchemas()

  const isReferenceType = type === 'reference' || type === 'reference_list'
  const canSubmit =
    !!fieldName.trim() &&
    !nameError(fieldName.trim()) &&
    (!isReferenceType || !!refSchema)
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
    setTimezone('')
  }

  const restrictionState: restrictions.RestrictionState = {
    min: minVal,
    max: maxVal,
    choices,
    maxLength,
    accept,
    maxSize,
    minDate,
    maxDate,
    refSchema,
    timezone,
  }
  const boundsError = restrictions.boundsProblem(type, restrictionState)

  function handleSubmit() {
    if (!canSubmit || boundsError) return
    const builtRestrictions = restrictions.build(type, restrictionState)

    if (mode === 'create') {
      const body: Parameters<typeof addField.mutate>[0] = {
        name: fieldName.trim(),
        type,
        required,
        restrictions: builtRestrictions,
      }
      if (fieldLabel.trim()) {
        body.label = fieldLabel.trim()
      }
      if (showDefault && defaultVal !== '') {
        body.default = defaultVal
      }
      addField.mutate(body, {
        onSuccess: () => {
          setFieldName('')
          setFieldLabel('')
          handleTypeChange('string')
          setRequired(false)
          onDone()
        },
      })
    } else {
      const trimmed = fieldName.trim()
      const trimmedLabel = fieldLabel.trim()
      updateField.mutate(
        {
          fieldName: editingField!.name,
          rename: trimmed !== editingField!.name ? trimmed : undefined,
          // '' clears the label; undefined leaves it untouched.
          label:
            trimmedLabel !== (editingField!.label ?? '')
              ? trimmedLabel
              : undefined,
          required,
          restrictions: builtRestrictions ?? {},
        },
        { onSuccess: onDone },
      )
    }
  }

  const mutation = mode === 'create' ? addField : updateField

  return (
    <FormGrid
      className={
        mode === 'create'
          ? 'bg-canvas-subtle px-4 py-3'
          : 'bg-accent-subtle px-4 py-3'
      }
    >
      <NameLabelFields
        kind="Field"
        value={{ label: fieldLabel, name: fieldName }}
        onChange={(next) => {
          setFieldLabel(next.label)
          setFieldName(next.name)
        }}
        // An existing name is what workflows reference — never re-derive it.
        deriveName={mode === 'create'}
        onEnter={handleSubmit}
        autoFocus
      />
      {mode === 'create' ? (
        <Field
          label="Type"
          span={4}
          hint="How values are stored and validated — pick reference to link to another record type."
        >
          <Select
            size="sm"
            value={type}
            onChange={(e) => handleTypeChange(e.target.value)}
          >
            {FIELD_TYPES.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </Select>
        </Field>
      ) : (
        <div className={`flex flex-col gap-1 ${spanClassName(4)}`}>
          <span className="text-xs font-medium text-fg-muted">Type</span>
          <div className="h-8 flex items-center">
            <Badge variant="accent">{type}</Badge>
          </div>
        </div>
      )}
      <Field label="Required" layout="inline" span={4}>
        <Checkbox
          checked={required}
          onChange={(e) => setRequired(e.target.checked)}
        />
      </Field>

      {isReferenceType && (
        <Field
          label="Target schema"
          span={6}
          required
          hint="Records in this field can only point to records of this type."
        >
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
                  {displayLabel(s.name, s.label)}
                </option>
              ))}
          </Select>
        </Field>
      )}

      {showDefault && (
        <Field label="Default value" span={4}>
          <Input
            size="sm"
            value={defaultVal}
            onChange={(e) => setDefaultVal(e.target.value)}
            placeholder="none"
          />
        </Field>
      )}

      {(type === 'integer' || type === 'float') && (
        <FormSection title="Restrictions">
          <Field label="Min" span={6}>
            <Input
              size="sm"
              type="number"
              step={type === 'integer' ? '1' : 'any'}
              value={minVal}
              onChange={(e) => setMinVal(e.target.value)}
              placeholder="none"
            />
          </Field>
          <Field label="Max" span={6}>
            <Input
              size="sm"
              type="number"
              step={type === 'integer' ? '1' : 'any'}
              value={maxVal}
              onChange={(e) => setMaxVal(e.target.value)}
              placeholder="none"
            />
          </Field>
        </FormSection>
      )}
      {(type === 'string' || type === 'enum') && (
        <FormSection title="Restrictions">
          <Field
            label="Choices (comma-separated)"
            span={type === 'string' ? 6 : 12}
          >
            <Input
              size="sm"
              value={choices}
              onChange={(e) => setChoices(e.target.value)}
              placeholder={
                mode === 'create' ? 'e.g. left,right,bilateral' : 'none'
              }
            />
          </Field>
          {type === 'string' && (
            <Field label="Max length" span={6}>
              <Input
                size="sm"
                type="number"
                step="1"
                min="1"
                value={maxLength}
                onChange={(e) => setMaxLength(e.target.value)}
                placeholder="none"
              />
            </Field>
          )}
        </FormSection>
      )}
      {(type === 'file' || type === 'file_list') && (
        <FormSection title="Restrictions">
          <Field
            label="Accept"
            span={6}
            hint="Comma-separated file extensions or MIME types to allow."
          >
            <Input
              size="sm"
              value={accept}
              onChange={(e) => setAccept(e.target.value)}
              placeholder=".csv,.txt"
            />
          </Field>
          <Field label="Max size (bytes)" span={6}>
            <Input
              size="sm"
              type="number"
              step="1"
              min="1"
              value={maxSize}
              onChange={(e) => setMaxSize(e.target.value)}
              placeholder="none"
            />
          </Field>
        </FormSection>
      )}
      {(type === 'date' || type === 'datetime') && (
        <FormSection title="Restrictions">
          {type === 'datetime' && (
            <Field
              label="Timezone"
              span={12}
              hint="Values without a UTC offset are read in this zone, and shown in it. Leave unset to use the collection's timezone."
            >
              <TimeZoneSelect
                size="sm"
                value={timezone}
                onChange={setTimezone}
                unsetLabel="Inherit from the collection"
              />
            </Field>
          )}
          <Field label="Not before" span={6}>
            <Input
              size="sm"
              type={type === 'date' ? 'date' : 'datetime-local'}
              value={minDate}
              onChange={(e) => setMinDate(e.target.value)}
            />
          </Field>
          <Field label="Not after" span={6}>
            <Input
              size="sm"
              type={type === 'date' ? 'date' : 'datetime-local'}
              value={maxDate}
              onChange={(e) => setMaxDate(e.target.value)}
            />
          </Field>
        </FormSection>
      )}

      {(boundsError || mutation.error) && (
        <p role="alert" className={`${spanClassName(12)} text-xs text-danger`}>
          {boundsError ?? errorMessage(mutation.error)}
        </p>
      )}

      <FormFooter>
        <Button
          variant="primary"
          size="sm"
          onClick={handleSubmit}
          disabled={mutation.isPending || !canSubmit || !!boundsError}
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
      </FormFooter>
    </FormGrid>
  )
}
