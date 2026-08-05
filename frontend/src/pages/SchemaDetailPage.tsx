import { useState, useCallback } from 'react'
import { useParams, useNavigate, Link } from 'react-router'
import { utcToDatetimeLocal, datetimeLocalToUTC } from '../utils/dates'
import { errorMessage } from '../lib/errors'
import {
  useSchema,
  useUpdateSchema,
  useAddField,
  useUpdateField,
  useDeleteSchema,
  useDeleteField,
  useSchemas,
  useReorderFields,
} from '../hooks/useSchemas'
import {
  Button,
  Badge,
  Table,
  Thead,
  Th,
  Tbody,
  Tr,
  Td,
  LoadingState,
  ErrorState,
} from '../components/ui'

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

// --- Inline metadata editor ---

function MetaEditor({
  schema,
  onDone,
}: {
  schema: { name: string; description: string | null }
  onDone: () => void
}) {
  const [name, setName] = useState(schema.name)
  const [description, setDescription] = useState(schema.description ?? '')
  const updateSchema = useUpdateSchema(schema.name)

  function handleSave() {
    const body: { rename?: string; description?: string } = {}
    if (name !== schema.name) body.rename = name
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
      <div className="flex flex-col gap-1">
        <label className="text-xs font-semibold text-fg-muted uppercase tracking-wide">
          Name
        </label>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="border border-border rounded-md px-3 py-1.5 text-sm bg-white focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent"
        />
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-xs font-semibold text-fg-muted uppercase tracking-wide">
          Description
        </label>
        <input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="No description"
          className="border border-border rounded-md px-3 py-1.5 text-sm bg-white focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent"
        />
      </div>
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

// --- Restrictions summary chip ---

function RestrictionsSummary({
  restrictions,
  type,
}: {
  restrictions: Record<string, unknown>
  type: string
}) {
  if (!restrictions || !Object.keys(restrictions).length) return null
  const parts: string[] = []
  if (type === 'integer' || type === 'float') {
    if (restrictions.min !== undefined) parts.push(`min ${restrictions.min}`)
    if (restrictions.max !== undefined) parts.push(`max ${restrictions.max}`)
  }
  if (type === 'string' || type === 'enum') {
    if (Array.isArray(restrictions.choices))
      parts.push(`choices: ${(restrictions.choices as string[]).join(', ')}`)
    if (restrictions.max_length !== undefined)
      parts.push(`max ${restrictions.max_length} chars`)
  }
  if (type === 'file' || type === 'file_list') {
    if (restrictions.accept) parts.push(`accept ${restrictions.accept}`)
    if (restrictions.max_size !== undefined) {
      const bytes = Number(restrictions.max_size)
      parts.push(
        `max ${bytes >= 1_048_576 ? `${(bytes / 1_048_576).toFixed(1)} MB` : bytes >= 1024 ? `${(bytes / 1024).toFixed(0)} KB` : `${bytes} B`}`,
      )
    }
  }
  if (type === 'date' || type === 'datetime') {
    if (restrictions.min !== undefined) parts.push(`from ${restrictions.min}`)
    if (restrictions.max !== undefined) parts.push(`until ${restrictions.max}`)
  }
  if (!parts.length) return null
  return (
    <span className="text-[10px] text-fg-muted leading-tight">
      {parts.join(' · ')}
    </span>
  )
}

// --- Add field form ---

const inputSm =
  'border border-border rounded-md px-2 py-1.5 text-sm bg-white focus:outline-none focus:border-accent focus:ring-1 focus:ring-accent'

function AddFieldForm({
  schemaName,
  onDone,
}: {
  schemaName: string
  onDone: () => void
}) {
  const [fieldName, setFieldName] = useState('')
  const [type, setType] = useState('string')
  const [required, setRequired] = useState(false)
  const [defaultVal, setDefaultVal] = useState('')
  // reference
  const [refSchema, setRefSchema] = useState('')
  // integer/float
  const [minVal, setMinVal] = useState('')
  const [maxVal, setMaxVal] = useState('')
  // string/enum
  const [choices, setChoices] = useState('')
  const [maxLength, setMaxLength] = useState('')
  // file/file_list
  const [accept, setAccept] = useState('')
  const [maxSize, setMaxSize] = useState('')
  // date/datetime
  const [minDate, setMinDate] = useState('')
  const [maxDate, setMaxDate] = useState('')

  const addField = useAddField(schemaName)
  const { data: allSchemas } = useSchemas()

  const canAdd = !!fieldName.trim() && (type !== 'reference' || !!refSchema)
  const showDefault = !NON_DEFAULT_TYPES.has(type)

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

  function buildRestrictions(): Record<string, unknown> | undefined {
    const r: Record<string, unknown> = {}
    if (type === 'reference' && refSchema) r.schema = refSchema
    if (type === 'integer' || type === 'float') {
      if (minVal !== '')
        r.min = type === 'integer' ? parseInt(minVal) : parseFloat(minVal)
      if (maxVal !== '')
        r.max = type === 'integer' ? parseInt(maxVal) : parseFloat(maxVal)
    }
    if (type === 'string' || type === 'enum') {
      if (choices.trim())
        r.choices = choices
          .split(',')
          .map((c) => c.trim())
          .filter(Boolean)
      if (maxLength !== '') r.max_length = parseInt(maxLength)
    }
    if (type === 'file' || type === 'file_list') {
      if (accept.trim()) r.accept = accept.trim()
      if (maxSize !== '') r.max_size = parseInt(maxSize)
    }
    if (type === 'date') {
      if (minDate) r.min = minDate
      if (maxDate) r.max = maxDate
    }
    if (type === 'datetime') {
      if (minDate) r.min = datetimeLocalToUTC(minDate)
      if (maxDate) r.max = datetimeLocalToUTC(maxDate)
    }
    return Object.keys(r).length ? r : undefined
  }

  function handleAdd() {
    if (!canAdd) return
    const body: Parameters<typeof addField.mutate>[0] = {
      name: fieldName.trim(),
      type,
      required,
      restrictions: buildRestrictions(),
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
  }

  return (
    <div className="border-t border-border bg-canvas-subtle px-4 py-3 flex flex-col gap-3">
      {/* Row 1: name, type, required */}
      <div className="flex items-center gap-3 flex-wrap">
        <input
          value={fieldName}
          onChange={(e) => setFieldName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
          placeholder="Field name"
          autoFocus
          className={`${inputSm} w-40`}
        />
        <select
          value={type}
          onChange={(e) => handleTypeChange(e.target.value)}
          className={inputSm}
        >
          {FIELD_TYPES.map((t) => (
            <option key={t}>{t}</option>
          ))}
        </select>
        {type === 'reference' && (
          <select
            value={refSchema}
            onChange={(e) => setRefSchema(e.target.value)}
            className={inputSm}
          >
            <option value="">— target schema —</option>
            {allSchemas
              ?.filter((s) => s.name !== schemaName)
              .map((s) => (
                <option key={s.id} value={s.name}>
                  {s.name}
                </option>
              ))}
          </select>
        )}
        <label className="flex items-center gap-1.5 text-sm text-fg cursor-pointer select-none">
          <input
            type="checkbox"
            checked={required}
            onChange={(e) => setRequired(e.target.checked)}
          />
          Required
        </label>
        <div className="flex gap-2 ml-auto">
          <Button
            variant="primary"
            size="sm"
            onClick={handleAdd}
            disabled={addField.isPending || !canAdd}
          >
            {addField.isPending ? 'Adding…' : 'Add field'}
          </Button>
          <Button size="sm" onClick={onDone}>
            Cancel
          </Button>
        </div>
      </div>

      {/* Default value */}
      {showDefault && (
        <div className="flex items-center gap-3 flex-wrap">
          <label className="flex items-center gap-1.5 text-xs text-fg-muted">
            Default value
            <input
              value={defaultVal}
              onChange={(e) => setDefaultVal(e.target.value)}
              placeholder="none"
              className={`${inputSm} w-40`}
            />
          </label>
        </div>
      )}

      {/* Row 2: type-specific restrictions */}
      {(type === 'integer' || type === 'float') && (
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-xs text-fg-muted font-medium">
            Restrictions:
          </span>
          <label className="flex items-center gap-1.5 text-xs text-fg-muted">
            Min
            <input
              type="number"
              step={type === 'integer' ? '1' : 'any'}
              value={minVal}
              onChange={(e) => setMinVal(e.target.value)}
              placeholder="none"
              className={`${inputSm} w-24`}
            />
          </label>
          <label className="flex items-center gap-1.5 text-xs text-fg-muted">
            Max
            <input
              type="number"
              step={type === 'integer' ? '1' : 'any'}
              value={maxVal}
              onChange={(e) => setMaxVal(e.target.value)}
              placeholder="none"
              className={`${inputSm} w-24`}
            />
          </label>
        </div>
      )}
      {(type === 'string' || type === 'enum') && (
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-xs text-fg-muted font-medium">
            Restrictions:
          </span>
          <label className="flex items-center gap-1.5 text-xs text-fg-muted">
            Choices (comma-separated)
            <input
              value={choices}
              onChange={(e) => setChoices(e.target.value)}
              placeholder="e.g. left,right,bilateral"
              className={`${inputSm} w-52`}
            />
          </label>
          {type === 'string' && (
            <label className="flex items-center gap-1.5 text-xs text-fg-muted">
              Max length
              <input
                type="number"
                step="1"
                min="1"
                value={maxLength}
                onChange={(e) => setMaxLength(e.target.value)}
                placeholder="none"
                className={`${inputSm} w-24`}
              />
            </label>
          )}
        </div>
      )}
      {(type === 'file' || type === 'file_list') && (
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-xs text-fg-muted font-medium">
            Restrictions:
          </span>
          <label className="flex items-center gap-1.5 text-xs text-fg-muted">
            Accept
            <input
              value={accept}
              onChange={(e) => setAccept(e.target.value)}
              placeholder=".csv,.txt"
              className={`${inputSm} w-36`}
            />
          </label>
          <label className="flex items-center gap-1.5 text-xs text-fg-muted">
            Max size (bytes)
            <input
              type="number"
              step="1"
              min="1"
              value={maxSize}
              onChange={(e) => setMaxSize(e.target.value)}
              placeholder="none"
              className={`${inputSm} w-28`}
            />
          </label>
        </div>
      )}
      {(type === 'date' || type === 'datetime') && (
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-xs text-fg-muted font-medium">
            Restrictions:
          </span>
          <label className="flex items-center gap-1.5 text-xs text-fg-muted">
            Not before
            <input
              type={type === 'date' ? 'date' : 'datetime-local'}
              value={minDate}
              onChange={(e) => setMinDate(e.target.value)}
              className={inputSm}
            />
          </label>
          <label className="flex items-center gap-1.5 text-xs text-fg-muted">
            Not after
            <input
              type={type === 'date' ? 'date' : 'datetime-local'}
              value={maxDate}
              onChange={(e) => setMaxDate(e.target.value)}
              className={inputSm}
            />
          </label>
        </div>
      )}

      {addField.error && (
        <span className="text-xs text-danger">
          {errorMessage(addField.error)}
        </span>
      )}
    </div>
  )
}

// --- Inline field editor ---

function FieldEditForm({
  field,
  schemaName,
  onDone,
}: {
  field: {
    id: string
    name: string
    type: string
    required: boolean
    restrictions: Record<string, unknown>
  }
  schemaName: string
  onDone: () => void
}) {
  const [name, setName] = useState(field.name)
  const [required, setRequired] = useState(field.required)
  const [minVal, setMinVal] = useState(
    field.restrictions?.min !== undefined ? String(field.restrictions.min) : '',
  )
  const [maxVal, setMaxVal] = useState(
    field.restrictions?.max !== undefined ? String(field.restrictions.max) : '',
  )
  const [choices, setChoices] = useState(
    Array.isArray(field.restrictions?.choices)
      ? (field.restrictions.choices as string[]).join(', ')
      : '',
  )
  const [maxLength, setMaxLength] = useState(
    field.restrictions?.max_length !== undefined
      ? String(field.restrictions.max_length)
      : '',
  )
  const [accept, setAccept] = useState(
    typeof field.restrictions?.accept === 'string'
      ? field.restrictions.accept
      : '',
  )
  const [maxSize, setMaxSize] = useState(
    field.restrictions?.max_size !== undefined
      ? String(field.restrictions.max_size)
      : '',
  )
  // date/datetime — stored as UTC ISO; display in datetime-local format
  const [minDate, setMinDate] = useState(
    field.restrictions?.min !== undefined
      ? field.type === 'datetime'
        ? utcToDatetimeLocal(String(field.restrictions.min))
        : String(field.restrictions.min)
      : '',
  )
  const [maxDate, setMaxDate] = useState(
    field.restrictions?.max !== undefined
      ? field.type === 'datetime'
        ? utcToDatetimeLocal(String(field.restrictions.max))
        : String(field.restrictions.max)
      : '',
  )

  const updateField = useUpdateField(schemaName)

  function buildRestrictions(): Record<string, unknown> {
    const r: Record<string, unknown> = {}
    if (field.type === 'reference' && field.restrictions?.schema)
      r.schema = field.restrictions.schema
    if (field.type === 'integer' || field.type === 'float') {
      if (minVal !== '')
        r.min = field.type === 'integer' ? parseInt(minVal) : parseFloat(minVal)
      if (maxVal !== '')
        r.max = field.type === 'integer' ? parseInt(maxVal) : parseFloat(maxVal)
    }
    if (field.type === 'string' || field.type === 'enum') {
      if (choices.trim())
        r.choices = choices
          .split(',')
          .map((c) => c.trim())
          .filter(Boolean)
      if (maxLength !== '') r.max_length = parseInt(maxLength)
    }
    if (field.type === 'file' || field.type === 'file_list') {
      if (accept.trim()) r.accept = accept.trim()
      if (maxSize !== '') r.max_size = parseInt(maxSize)
    }
    if (field.type === 'date') {
      if (minDate) r.min = minDate
      if (maxDate) r.max = maxDate
    }
    if (field.type === 'datetime') {
      if (minDate) r.min = datetimeLocalToUTC(minDate)
      if (maxDate) r.max = datetimeLocalToUTC(maxDate)
    }
    return r
  }

  function handleSave() {
    const trimmed = name.trim()
    updateField.mutate(
      {
        fieldName: field.name,
        rename: trimmed !== field.name ? trimmed : undefined,
        required,
        restrictions: buildRestrictions(),
      },
      { onSuccess: onDone },
    )
  }

  const dtype = field.type

  return (
    <div className="bg-accent-subtle border-t border-border px-4 py-3 flex flex-col gap-3">
      <div className="flex items-center gap-3 flex-wrap">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSave()}
          autoFocus
          className={`${inputSm} w-40`}
        />
        <Badge variant="accent">{dtype}</Badge>
        <label className="flex items-center gap-1.5 text-sm text-fg cursor-pointer select-none">
          <input
            type="checkbox"
            checked={required}
            onChange={(e) => setRequired(e.target.checked)}
          />
          Required
        </label>
        <div className="flex gap-2 ml-auto">
          <Button
            variant="primary"
            size="sm"
            onClick={handleSave}
            disabled={updateField.isPending || !name.trim()}
          >
            {updateField.isPending ? 'Saving…' : 'Save'}
          </Button>
          <Button size="sm" onClick={onDone}>
            Cancel
          </Button>
        </div>
      </div>

      {(dtype === 'integer' || dtype === 'float') && (
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-xs text-fg-muted font-medium">
            Restrictions:
          </span>
          <label className="flex items-center gap-1.5 text-xs text-fg-muted">
            Min
            <input
              type="number"
              step={dtype === 'integer' ? '1' : 'any'}
              value={minVal}
              onChange={(e) => setMinVal(e.target.value)}
              placeholder="none"
              className={`${inputSm} w-24`}
            />
          </label>
          <label className="flex items-center gap-1.5 text-xs text-fg-muted">
            Max
            <input
              type="number"
              step={dtype === 'integer' ? '1' : 'any'}
              value={maxVal}
              onChange={(e) => setMaxVal(e.target.value)}
              placeholder="none"
              className={`${inputSm} w-24`}
            />
          </label>
        </div>
      )}
      {(dtype === 'string' || dtype === 'enum') && (
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-xs text-fg-muted font-medium">
            Restrictions:
          </span>
          <label className="flex items-center gap-1.5 text-xs text-fg-muted">
            Choices (comma-separated)
            <input
              value={choices}
              onChange={(e) => setChoices(e.target.value)}
              placeholder="none"
              className={`${inputSm} w-52`}
            />
          </label>
          {dtype === 'string' && (
            <label className="flex items-center gap-1.5 text-xs text-fg-muted">
              Max length
              <input
                type="number"
                step="1"
                min="1"
                value={maxLength}
                onChange={(e) => setMaxLength(e.target.value)}
                placeholder="none"
                className={`${inputSm} w-24`}
              />
            </label>
          )}
        </div>
      )}
      {(dtype === 'file' || dtype === 'file_list') && (
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-xs text-fg-muted font-medium">
            Restrictions:
          </span>
          <label className="flex items-center gap-1.5 text-xs text-fg-muted">
            Accept
            <input
              value={accept}
              onChange={(e) => setAccept(e.target.value)}
              placeholder=".csv,.txt"
              className={`${inputSm} w-36`}
            />
          </label>
          <label className="flex items-center gap-1.5 text-xs text-fg-muted">
            Max size (bytes)
            <input
              type="number"
              step="1"
              min="1"
              value={maxSize}
              onChange={(e) => setMaxSize(e.target.value)}
              placeholder="none"
              className={`${inputSm} w-28`}
            />
          </label>
        </div>
      )}
      {(dtype === 'date' || dtype === 'datetime') && (
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-xs text-fg-muted font-medium">
            Restrictions:
          </span>
          <label className="flex items-center gap-1.5 text-xs text-fg-muted">
            Not before
            <input
              type={dtype === 'date' ? 'date' : 'datetime-local'}
              value={minDate}
              onChange={(e) => setMinDate(e.target.value)}
              className={inputSm}
            />
          </label>
          <label className="flex items-center gap-1.5 text-xs text-fg-muted">
            Not after
            <input
              type={dtype === 'date' ? 'date' : 'datetime-local'}
              value={maxDate}
              onChange={(e) => setMaxDate(e.target.value)}
              className={inputSm}
            />
          </label>
        </div>
      )}
      {updateField.error && (
        <span className="text-xs text-danger">
          {errorMessage(updateField.error)}
        </span>
      )}
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

  if (isLoading) return <LoadingState />
  if (error || !schema)
    return (
      <ErrorState message={error ? errorMessage(error) : 'Schema not found'} />
    )

  const parentSchema = schema.parent_id
    ? allSchemas?.find((s) => s.id === schema.parent_id)
    : null

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-1.5 text-sm text-fg-muted">
        <Link to="/schemas" className="hover:text-accent">
          Schemas
        </Link>
        <span>/</span>
        <span className="text-fg font-medium">{schema.name}</span>
      </nav>

      {/* Header */}
      <div>
        {editing ? (
          <MetaEditor schema={schema} onDone={() => setEditing(false)} />
        ) : (
          <div className="flex items-start justify-between">
            <div>
              <h1 className="text-xl font-semibold text-fg">
                {schema.name}
              </h1>
              <p className="mt-0.5 text-sm text-fg-muted">
                {schema.description ?? (
                  <span className="italic">No description</span>
                )}
              </p>
              {parentSchema && (
                <p className="mt-1 text-sm text-fg-muted">
                  Inherits from{' '}
                  <Link
                    to={`/schemas/${parentSchema.id}`}
                    className="text-accent hover:underline"
                  >
                    {parentSchema.name}
                  </Link>
                </p>
              )}
            </div>
            <Button size="sm" onClick={() => setEditing(true)}>
              Edit
            </Button>
          </div>
        )}
      </div>

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
                <tr key={field.id} className="bg-white">
                  <td colSpan={5} className="p-0">
                    <FieldEditForm
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
                  className={`bg-white transition-colors ${
                    dragOverIndex === index && dragSrcIndex !== index
                      ? 'bg-accent-subtle outline outline-2 outline-accent'
                      : dragSrcIndex === index
                        ? 'opacity-50'
                        : ''
                  }`}
                >
                  {/* Drag handle + reorder buttons */}
                  <Td className="w-8 cursor-grab text-border hover:text-fg-muted select-none">
                    <div className="flex flex-col items-center gap-0.5">
                      <button
                        type="button"
                        title="Move up"
                        disabled={index === 0 || reorderFields.isPending}
                        onClick={() => moveField(index, 'up')}
                        className="text-[10px] text-border hover:text-fg disabled:opacity-30 leading-none"
                      >
                        ▲
                      </button>
                      <span className="text-xs" title="Drag to reorder">
                        ⠿
                      </span>
                      <button
                        type="button"
                        title="Move down"
                        disabled={
                          index === schema.fields.length - 1 ||
                          reorderFields.isPending
                        }
                        onClick={() => moveField(index, 'down')}
                        className="text-[10px] text-border hover:text-fg disabled:opacity-30 leading-none"
                      >
                        ▼
                      </button>
                    </div>
                  </Td>
                  <Td>
                    <span className="flex flex-col gap-0.5">
                      <span className="flex items-center gap-1.5">
                        <span className="font-mono text-sm">{field.name}</span>
                        {schema.display_fields.includes(field.name) && (
                          <span
                            className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-attention-subtle text-attention border border-attention-muted"
                            title="Display field — included in the record's natural name"
                          >
                            display
                            {schema.display_fields.length > 1 &&
                              ` #${schema.display_fields.indexOf(field.name) + 1}`}
                          </span>
                        )}
                      </span>
                      {field.default !== null &&
                        field.default !== undefined && (
                          <span className="text-[11px] text-attention">
                            default: {String(field.default)}
                          </span>
                        )}
                    </span>
                  </Td>
                  <Td>
                    <div className="flex flex-col gap-0.5">
                      <div className="flex items-center gap-1.5">
                        <Badge variant="accent">{field.type}</Badge>
                        {field.type === 'reference' &&
                          !!field.restrictions?.schema && (
                            <span className="text-xs text-fg-muted">
                              {'→ '}
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
                      className={`text-xs font-medium px-2 py-0.5 rounded-full border cursor-pointer transition-colors ${
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
                      {confirmDeleteField === field.name ? (
                        <>
                          <button
                            onClick={() =>
                              deleteField.mutate(field.name, {
                                onSuccess: () => setConfirmDeleteField(null),
                              })
                            }
                            disabled={deleteField.isPending}
                            className="text-xs text-danger font-medium hover:underline disabled:opacity-50"
                          >
                            Confirm
                          </button>
                          <button
                            onClick={() => setConfirmDeleteField(null)}
                            className="text-xs text-fg-muted hover:underline"
                          >
                            Cancel
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            onClick={() => toggleDisplayField(field.name)}
                            className={`text-xs transition-colors ${schema.display_fields.includes(field.name) ? 'text-attention' : 'text-border hover:text-attention'}`}
                            title={
                              schema.display_fields.includes(field.name)
                                ? 'Remove from display fields'
                                : 'Add to display fields'
                            }
                          >
                            ★
                          </button>
                          {schema.display_fields.length > 1 &&
                            schema.display_fields.includes(field.name) && (
                              <span className="flex flex-col items-center gap-0.5">
                                <button
                                  type="button"
                                  title="Move earlier in display order"
                                  disabled={
                                    schema.display_fields.indexOf(
                                      field.name,
                                    ) === 0 || updateSchema.isPending
                                  }
                                  onClick={() =>
                                    moveDisplayField(field.name, 'up')
                                  }
                                  className="text-[9px] text-attention hover:text-attention-emphasis disabled:opacity-30 leading-none"
                                >
                                  ▲
                                </button>
                                <button
                                  type="button"
                                  title="Move later in display order"
                                  disabled={
                                    schema.display_fields.indexOf(
                                      field.name,
                                    ) ===
                                      schema.display_fields.length - 1 ||
                                    updateSchema.isPending
                                  }
                                  onClick={() =>
                                    moveDisplayField(field.name, 'down')
                                  }
                                  className="text-[9px] text-attention hover:text-attention-emphasis disabled:opacity-30 leading-none"
                                >
                                  ▼
                                </button>
                              </span>
                            )}
                          <button
                            onClick={() => {
                              setConfirmDeleteField(null)
                              setEditingField(field.name)
                            }}
                            className="text-xs text-fg-muted hover:text-accent transition-colors"
                            title="Edit field"
                          >
                            ✎
                          </button>
                          <button
                            onClick={() => {
                              setEditingField(null)
                              setConfirmDeleteField(field.name)
                            }}
                            className="text-xs text-fg-muted hover:text-danger transition-colors"
                            title="Remove field"
                          >
                            ✕
                          </button>
                        </>
                      )}
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
                  <AddFieldForm
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
            <p className="text-sm font-medium text-fg">
              Delete this schema
            </p>
            <p className="text-xs text-fg-muted">
              This cannot be undone. All field definitions will be removed.
            </p>
          </div>
          {confirmDelete ? (
            <div className="flex items-center gap-2">
              <span className="text-xs text-fg-muted">Are you sure?</span>
              <Button
                variant="danger"
                size="sm"
                onClick={() =>
                  deleteSchema.mutate(schema.name, {
                    onSuccess: () => navigate('/schemas'),
                  })
                }
                disabled={deleteSchema.isPending}
              >
                {deleteSchema.isPending ? 'Deleting…' : 'Confirm delete'}
              </Button>
              <Button size="sm" onClick={() => setConfirmDelete(false)}>
                Cancel
              </Button>
            </div>
          ) : (
            <Button
              variant="danger"
              size="sm"
              onClick={() => setConfirmDelete(true)}
            >
              Delete schema
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}
