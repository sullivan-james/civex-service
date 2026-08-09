import { useState, useCallback } from 'react'
import { useParams, useNavigate, Link } from 'react-router'
import * as restrictions from '../utils/restrictions'
import type { Field } from '../api/schemas'
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
  Input,
  Select,
  Checkbox,
  ConfirmDialog,
} from '../components/ui'
import {
  Star,
  Pencil,
  X,
  ChevronUp,
  ChevronDown,
  GripVertical,
  ArrowRight,
} from '../components/ui/icons'

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
        <Input value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-xs font-semibold text-fg-muted uppercase tracking-wide">
          Description
        </label>
        <Input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="No description"
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
  restrictions: fieldRestrictions,
  type,
}: {
  restrictions: Record<string, unknown>
  type: string
}) {
  const summary = restrictions.summarise(fieldRestrictions, type)
  if (!summary) return null
  return <span className="text-xs text-fg-muted leading-tight">{summary}</span>
}

// --- Add field form ---

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

  function handleAdd() {
    if (!canAdd) return
    const body: Parameters<typeof addField.mutate>[0] = {
      name: fieldName.trim(),
      type,
      required,
      restrictions: restrictions.build(type, {
        min: minVal,
        max: maxVal,
        choices,
        maxLength,
        accept,
        maxSize,
        minDate,
        maxDate,
        refSchema,
      }),
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
        <Input
          size="sm"
          value={fieldName}
          onChange={(e) => setFieldName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
          placeholder="Field name"
          autoFocus
          className="w-40"
        />
        <Select
          size="sm"
          value={type}
          onChange={(e) => handleTypeChange(e.target.value)}
        >
          {FIELD_TYPES.map((t) => (
            <option key={t}>{t}</option>
          ))}
        </Select>
        {type === 'reference' && (
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
        <label className="flex items-center gap-2 text-sm text-fg cursor-pointer select-none">
          <Checkbox
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
          <label className="flex items-center gap-2 text-xs text-fg-muted">
            Default value
            <Input
              size="sm"
              value={defaultVal}
              onChange={(e) => setDefaultVal(e.target.value)}
              placeholder="none"
              className="w-40"
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
          <label className="flex items-center gap-2 text-xs text-fg-muted">
            Min
            <Input
              size="sm"
              type="number"
              step={type === 'integer' ? '1' : 'any'}
              value={minVal}
              onChange={(e) => setMinVal(e.target.value)}
              placeholder="none"
              className="w-24"
            />
          </label>
          <label className="flex items-center gap-2 text-xs text-fg-muted">
            Max
            <Input
              size="sm"
              type="number"
              step={type === 'integer' ? '1' : 'any'}
              value={maxVal}
              onChange={(e) => setMaxVal(e.target.value)}
              placeholder="none"
              className="w-24"
            />
          </label>
        </div>
      )}
      {(type === 'string' || type === 'enum') && (
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-xs text-fg-muted font-medium">
            Restrictions:
          </span>
          <label className="flex items-center gap-2 text-xs text-fg-muted">
            Choices (comma-separated)
            <Input
              size="sm"
              value={choices}
              onChange={(e) => setChoices(e.target.value)}
              placeholder="e.g. left,right,bilateral"
              className="w-52"
            />
          </label>
          {type === 'string' && (
            <label className="flex items-center gap-2 text-xs text-fg-muted">
              Max length
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
            </label>
          )}
        </div>
      )}
      {(type === 'file' || type === 'file_list') && (
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-xs text-fg-muted font-medium">
            Restrictions:
          </span>
          <label className="flex items-center gap-2 text-xs text-fg-muted">
            Accept
            <Input
              size="sm"
              value={accept}
              onChange={(e) => setAccept(e.target.value)}
              placeholder=".csv,.txt"
              className="w-36"
            />
          </label>
          <label className="flex items-center gap-2 text-xs text-fg-muted">
            Max size (bytes)
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
          </label>
        </div>
      )}
      {(type === 'date' || type === 'datetime') && (
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-xs text-fg-muted font-medium">
            Restrictions:
          </span>
          <label className="flex items-center gap-2 text-xs text-fg-muted">
            Not before
            <Input
              size="sm"
              type={type === 'date' ? 'date' : 'datetime-local'}
              value={minDate}
              onChange={(e) => setMinDate(e.target.value)}
            />
          </label>
          <label className="flex items-center gap-2 text-xs text-fg-muted">
            Not after
            <Input
              size="sm"
              type={type === 'date' ? 'date' : 'datetime-local'}
              value={maxDate}
              onChange={(e) => setMaxDate(e.target.value)}
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
  field: Field
  schemaName: string
  onDone: () => void
}) {
  const [name, setName] = useState(field.name)
  const [required, setRequired] = useState(field.required)
  const initialRestrictions = restrictions.parse(field)
  const [minVal, setMinVal] = useState(initialRestrictions.min)
  const [maxVal, setMaxVal] = useState(initialRestrictions.max)
  const [choices, setChoices] = useState(initialRestrictions.choices)
  const [maxLength, setMaxLength] = useState(initialRestrictions.maxLength)
  const [accept, setAccept] = useState(initialRestrictions.accept)
  const [maxSize, setMaxSize] = useState(initialRestrictions.maxSize)
  // date/datetime — stored as UTC ISO; display in datetime-local format
  const [minDate, setMinDate] = useState(initialRestrictions.minDate)
  const [maxDate, setMaxDate] = useState(initialRestrictions.maxDate)

  const updateField = useUpdateField(schemaName)

  function handleSave() {
    const trimmed = name.trim()
    updateField.mutate(
      {
        fieldName: field.name,
        rename: trimmed !== field.name ? trimmed : undefined,
        required,
        restrictions:
          restrictions.build(field.type, {
            min: minVal,
            max: maxVal,
            choices,
            maxLength,
            accept,
            maxSize,
            minDate,
            maxDate,
            refSchema: initialRestrictions.refSchema,
          }) ?? {},
      },
      { onSuccess: onDone },
    )
  }

  const dtype = field.type

  return (
    <div className="bg-accent-subtle border-t border-border px-4 py-3 flex flex-col gap-3">
      <div className="flex items-center gap-3 flex-wrap">
        <Input
          size="sm"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSave()}
          autoFocus
          className="w-40"
        />
        <Badge variant="accent">{dtype}</Badge>
        <label className="flex items-center gap-2 text-sm text-fg cursor-pointer select-none">
          <Checkbox
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
          <label className="flex items-center gap-2 text-xs text-fg-muted">
            Min
            <Input
              size="sm"
              type="number"
              step={dtype === 'integer' ? '1' : 'any'}
              value={minVal}
              onChange={(e) => setMinVal(e.target.value)}
              placeholder="none"
              className="w-24"
            />
          </label>
          <label className="flex items-center gap-2 text-xs text-fg-muted">
            Max
            <Input
              size="sm"
              type="number"
              step={dtype === 'integer' ? '1' : 'any'}
              value={maxVal}
              onChange={(e) => setMaxVal(e.target.value)}
              placeholder="none"
              className="w-24"
            />
          </label>
        </div>
      )}
      {(dtype === 'string' || dtype === 'enum') && (
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-xs text-fg-muted font-medium">
            Restrictions:
          </span>
          <label className="flex items-center gap-2 text-xs text-fg-muted">
            Choices (comma-separated)
            <Input
              size="sm"
              value={choices}
              onChange={(e) => setChoices(e.target.value)}
              placeholder="none"
              className="w-52"
            />
          </label>
          {dtype === 'string' && (
            <label className="flex items-center gap-2 text-xs text-fg-muted">
              Max length
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
            </label>
          )}
        </div>
      )}
      {(dtype === 'file' || dtype === 'file_list') && (
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-xs text-fg-muted font-medium">
            Restrictions:
          </span>
          <label className="flex items-center gap-2 text-xs text-fg-muted">
            Accept
            <Input
              size="sm"
              value={accept}
              onChange={(e) => setAccept(e.target.value)}
              placeholder=".csv,.txt"
              className="w-36"
            />
          </label>
          <label className="flex items-center gap-2 text-xs text-fg-muted">
            Max size (bytes)
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
          </label>
        </div>
      )}
      {(dtype === 'date' || dtype === 'datetime') && (
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-xs text-fg-muted font-medium">
            Restrictions:
          </span>
          <label className="flex items-center gap-2 text-xs text-fg-muted">
            Not before
            <Input
              size="sm"
              type={dtype === 'date' ? 'date' : 'datetime-local'}
              value={minDate}
              onChange={(e) => setMinDate(e.target.value)}
            />
          </label>
          <label className="flex items-center gap-2 text-xs text-fg-muted">
            Not after
            <Input
              size="sm"
              type={dtype === 'date' ? 'date' : 'datetime-local'}
              value={maxDate}
              onChange={(e) => setMaxDate(e.target.value)}
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

  if (isLoading)
    return (
      <div className="space-y-6">
        <DetailSkeleton metadataRows={0} sections={0} />
        <TableSkeleton
          columns={['w-8', 'w-32', 'w-20', 'w-16', 'w-24']}
          rows={6}
        />
      </div>
    )
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
      <nav className="flex items-center gap-2 text-sm text-fg-muted">
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
              <h1 className="text-xl font-semibold text-fg">{schema.name}</h1>
              <p className="mt-1 text-sm text-fg-muted">
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
                <tr key={field.id} className="bg-canvas">
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
                        <span className="font-mono text-sm">{field.name}</span>
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
    </div>
  )
}
