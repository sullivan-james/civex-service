import { useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { utcToDatetimeLocal, datetimeLocalToUTC } from '../utils/dates'
import { useSchema, useUpdateSchema, useAddField, useUpdateField, useDeleteSchema, useDeleteField, useSchemas } from '../hooks/useSchemas'
import {
  Button, Badge,
  Table, Thead, Th, Tbody, Tr, Td,
  LoadingState, ErrorState,
} from '../components/ui'

const FIELD_TYPES = ['string', 'integer', 'float', 'boolean', 'date', 'datetime', 'file', 'reference']

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
    if (description !== (schema.description ?? '')) body.description = description
    if (!Object.keys(body).length) { onDone(); return }
    updateSchema.mutate(body, { onSuccess: onDone })
  }

  return (
    <div className="border border-[#d0d7de] rounded-md p-4 bg-[#f6f8fa] mb-4 flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <label className="text-xs font-semibold text-[#656d76] uppercase tracking-wide">Name</label>
        <input
          value={name}
          onChange={e => setName(e.target.value)}
          className="border border-[#d0d7de] rounded-md px-3 py-1.5 text-sm bg-white focus:outline-none focus:border-[#0969da] focus:ring-1 focus:ring-[#0969da]"
        />
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-xs font-semibold text-[#656d76] uppercase tracking-wide">Description</label>
        <input
          value={description}
          onChange={e => setDescription(e.target.value)}
          placeholder="No description"
          className="border border-[#d0d7de] rounded-md px-3 py-1.5 text-sm bg-white focus:outline-none focus:border-[#0969da] focus:ring-1 focus:ring-[#0969da]"
        />
      </div>
      {updateSchema.error && (
        <p className="text-xs text-[#d1242f]">{String(updateSchema.error)}</p>
      )}
      <div className="flex gap-2">
        <Button variant="primary" size="sm" onClick={handleSave} disabled={updateSchema.isPending}>
          {updateSchema.isPending ? 'Saving…' : 'Save'}
        </Button>
        <Button size="sm" onClick={onDone}>Cancel</Button>
      </div>
    </div>
  )
}

// --- Restrictions summary chip ---

function RestrictionsSummary({ restrictions, type }: { restrictions: Record<string, unknown>; type: string }) {
  if (!restrictions || !Object.keys(restrictions).length) return null
  const parts: string[] = []
  if (type === 'integer' || type === 'float') {
    if (restrictions.min !== undefined) parts.push(`min ${restrictions.min}`)
    if (restrictions.max !== undefined) parts.push(`max ${restrictions.max}`)
  }
  if (type === 'string') {
    if (Array.isArray(restrictions.choices)) parts.push(`choices: ${(restrictions.choices as string[]).join(', ')}`)
    if (restrictions.max_length !== undefined) parts.push(`max ${restrictions.max_length} chars`)
  }
  if (type === 'file' || type === 'file_list') {
    if (restrictions.accept) parts.push(`accept ${restrictions.accept}`)
    if (restrictions.max_size !== undefined) {
      const bytes = Number(restrictions.max_size)
      parts.push(`max ${bytes >= 1_048_576 ? `${(bytes / 1_048_576).toFixed(1)} MB` : bytes >= 1024 ? `${(bytes / 1024).toFixed(0)} KB` : `${bytes} B`}`)
    }
  }
  if (type === 'date' || type === 'datetime') {
    if (restrictions.min !== undefined) parts.push(`from ${restrictions.min}`)
    if (restrictions.max !== undefined) parts.push(`until ${restrictions.max}`)
  }
  if (!parts.length) return null
  return <span className="text-[10px] text-[#656d76] leading-tight">{parts.join(' · ')}</span>
}

// --- Add field form ---

const inputSm = 'border border-[#d0d7de] rounded-md px-2 py-1.5 text-sm bg-white focus:outline-none focus:border-[#0969da] focus:ring-1 focus:ring-[#0969da]'

function AddFieldForm({ schemaName, onDone }: { schemaName: string; onDone: () => void }) {
  const [fieldName, setFieldName] = useState('')
  const [type, setType] = useState('string')
  const [required, setRequired] = useState(false)
  // reference
  const [refSchema, setRefSchema] = useState('')
  // integer/float
  const [minVal, setMinVal] = useState('')
  const [maxVal, setMaxVal] = useState('')
  // string
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

  function handleTypeChange(t: string) {
    setType(t)
    setRefSchema(''); setMinVal(''); setMaxVal(''); setChoices(''); setMaxLength(''); setAccept(''); setMaxSize(''); setMinDate(''); setMaxDate('')
  }

  function buildRestrictions(): Record<string, unknown> | undefined {
    const r: Record<string, unknown> = {}
    if (type === 'reference' && refSchema) r.schema = refSchema
    if (type === 'integer' || type === 'float') {
      if (minVal !== '') r.min = type === 'integer' ? parseInt(minVal) : parseFloat(minVal)
      if (maxVal !== '') r.max = type === 'integer' ? parseInt(maxVal) : parseFloat(maxVal)
    }
    if (type === 'string') {
      if (choices.trim()) r.choices = choices.split(',').map(c => c.trim()).filter(Boolean)
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
    addField.mutate(
      { name: fieldName.trim(), type, required, restrictions: buildRestrictions() },
      { onSuccess: () => { setFieldName(''); handleTypeChange('string'); setRequired(false); onDone() } },
    )
  }

  return (
    <div className="border-t border-[#d0d7de] bg-[#f6f8fa] px-4 py-3 flex flex-col gap-3">
      {/* Row 1: name, type, required */}
      <div className="flex items-center gap-3 flex-wrap">
        <input
          value={fieldName}
          onChange={e => setFieldName(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleAdd()}
          placeholder="Field name"
          autoFocus
          className={`${inputSm} w-40`}
        />
        <select
          value={type}
          onChange={e => handleTypeChange(e.target.value)}
          className={inputSm}
        >
          {FIELD_TYPES.map(t => <option key={t}>{t}</option>)}
        </select>
        {type === 'reference' && (
          <select
            value={refSchema}
            onChange={e => setRefSchema(e.target.value)}
            className={inputSm}
          >
            <option value="">— target schema —</option>
            {allSchemas?.filter(s => s.name !== schemaName).map(s => (
              <option key={s.id} value={s.name}>{s.name}</option>
            ))}
          </select>
        )}
        <label className="flex items-center gap-1.5 text-sm text-[#1f2328] cursor-pointer select-none">
          <input type="checkbox" checked={required} onChange={e => setRequired(e.target.checked)} />
          Required
        </label>
        <div className="flex gap-2 ml-auto">
          <Button variant="primary" size="sm" onClick={handleAdd} disabled={addField.isPending || !canAdd}>
            {addField.isPending ? 'Adding…' : 'Add field'}
          </Button>
          <Button size="sm" onClick={onDone}>Cancel</Button>
        </div>
      </div>

      {/* Row 2: type-specific restrictions */}
      {(type === 'integer' || type === 'float') && (
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-xs text-[#656d76] font-medium">Restrictions:</span>
          <label className="flex items-center gap-1.5 text-xs text-[#656d76]">
            Min
            <input type="number" step={type === 'integer' ? '1' : 'any'} value={minVal} onChange={e => setMinVal(e.target.value)} placeholder="none" className={`${inputSm} w-24`} />
          </label>
          <label className="flex items-center gap-1.5 text-xs text-[#656d76]">
            Max
            <input type="number" step={type === 'integer' ? '1' : 'any'} value={maxVal} onChange={e => setMaxVal(e.target.value)} placeholder="none" className={`${inputSm} w-24`} />
          </label>
        </div>
      )}
      {type === 'string' && (
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-xs text-[#656d76] font-medium">Restrictions:</span>
          <label className="flex items-center gap-1.5 text-xs text-[#656d76]">
            Choices (comma-separated)
            <input value={choices} onChange={e => setChoices(e.target.value)} placeholder="e.g. left,right,bilateral" className={`${inputSm} w-52`} />
          </label>
          <label className="flex items-center gap-1.5 text-xs text-[#656d76]">
            Max length
            <input type="number" step="1" min="1" value={maxLength} onChange={e => setMaxLength(e.target.value)} placeholder="none" className={`${inputSm} w-24`} />
          </label>
        </div>
      )}
      {(type === 'file' || type === 'file_list') && (
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-xs text-[#656d76] font-medium">Restrictions:</span>
          <label className="flex items-center gap-1.5 text-xs text-[#656d76]">
            Accept
            <input value={accept} onChange={e => setAccept(e.target.value)} placeholder=".csv,.txt" className={`${inputSm} w-36`} />
          </label>
          <label className="flex items-center gap-1.5 text-xs text-[#656d76]">
            Max size (bytes)
            <input type="number" step="1" min="1" value={maxSize} onChange={e => setMaxSize(e.target.value)} placeholder="none" className={`${inputSm} w-28`} />
          </label>
        </div>
      )}
      {(type === 'date' || type === 'datetime') && (
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-xs text-[#656d76] font-medium">Restrictions:</span>
          <label className="flex items-center gap-1.5 text-xs text-[#656d76]">
            Not before
            <input type={type === 'date' ? 'date' : 'datetime-local'} value={minDate} onChange={e => setMinDate(e.target.value)} className={inputSm} />
          </label>
          <label className="flex items-center gap-1.5 text-xs text-[#656d76]">
            Not after
            <input type={type === 'date' ? 'date' : 'datetime-local'} value={maxDate} onChange={e => setMaxDate(e.target.value)} className={inputSm} />
          </label>
        </div>
      )}

      {addField.error && <span className="text-xs text-[#d1242f]">{String(addField.error)}</span>}
    </div>
  )
}

// --- Inline field editor ---

function FieldEditForm({ field, schemaName, onDone }: { field: { id: string; name: string; type: string; required: boolean; restrictions: Record<string, unknown> }; schemaName: string; onDone: () => void }) {
  const [name, setName] = useState(field.name)
  const [required, setRequired] = useState(field.required)
  const [minVal, setMinVal] = useState(field.restrictions?.min !== undefined ? String(field.restrictions.min) : '')
  const [maxVal, setMaxVal] = useState(field.restrictions?.max !== undefined ? String(field.restrictions.max) : '')
  const [choices, setChoices] = useState(Array.isArray(field.restrictions?.choices) ? (field.restrictions.choices as string[]).join(', ') : '')
  const [maxLength, setMaxLength] = useState(field.restrictions?.max_length !== undefined ? String(field.restrictions.max_length) : '')
  const [accept, setAccept] = useState(typeof field.restrictions?.accept === 'string' ? field.restrictions.accept : '')
  const [maxSize, setMaxSize] = useState(field.restrictions?.max_size !== undefined ? String(field.restrictions.max_size) : '')
  // date/datetime — stored as UTC ISO; display in datetime-local format
  const [minDate, setMinDate] = useState(
    field.restrictions?.min !== undefined
      ? (field.type === 'datetime' ? utcToDatetimeLocal(String(field.restrictions.min)) : String(field.restrictions.min))
      : ''
  )
  const [maxDate, setMaxDate] = useState(
    field.restrictions?.max !== undefined
      ? (field.type === 'datetime' ? utcToDatetimeLocal(String(field.restrictions.max)) : String(field.restrictions.max))
      : ''
  )

  const updateField = useUpdateField(schemaName)

  function buildRestrictions(): Record<string, unknown> {
    const r: Record<string, unknown> = {}
    if (field.type === 'reference' && field.restrictions?.schema) r.schema = field.restrictions.schema
    if (field.type === 'integer' || field.type === 'float') {
      if (minVal !== '') r.min = field.type === 'integer' ? parseInt(minVal) : parseFloat(minVal)
      if (maxVal !== '') r.max = field.type === 'integer' ? parseInt(maxVal) : parseFloat(maxVal)
    }
    if (field.type === 'string') {
      if (choices.trim()) r.choices = choices.split(',').map(c => c.trim()).filter(Boolean)
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
    <div className="bg-[#f0f6ff] border-t border-[#d0d7de] px-4 py-3 flex flex-col gap-3">
      <div className="flex items-center gap-3 flex-wrap">
        <input
          value={name}
          onChange={e => setName(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleSave()}
          autoFocus
          className={`${inputSm} w-40`}
        />
        <Badge variant="accent">{dtype}</Badge>
        <label className="flex items-center gap-1.5 text-sm text-[#1f2328] cursor-pointer select-none">
          <input type="checkbox" checked={required} onChange={e => setRequired(e.target.checked)} />
          Required
        </label>
        <div className="flex gap-2 ml-auto">
          <Button variant="primary" size="sm" onClick={handleSave} disabled={updateField.isPending || !name.trim()}>
            {updateField.isPending ? 'Saving…' : 'Save'}
          </Button>
          <Button size="sm" onClick={onDone}>Cancel</Button>
        </div>
      </div>

      {(dtype === 'integer' || dtype === 'float') && (
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-xs text-[#656d76] font-medium">Restrictions:</span>
          <label className="flex items-center gap-1.5 text-xs text-[#656d76]">
            Min
            <input type="number" step={dtype === 'integer' ? '1' : 'any'} value={minVal} onChange={e => setMinVal(e.target.value)} placeholder="none" className={`${inputSm} w-24`} />
          </label>
          <label className="flex items-center gap-1.5 text-xs text-[#656d76]">
            Max
            <input type="number" step={dtype === 'integer' ? '1' : 'any'} value={maxVal} onChange={e => setMaxVal(e.target.value)} placeholder="none" className={`${inputSm} w-24`} />
          </label>
        </div>
      )}
      {dtype === 'string' && (
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-xs text-[#656d76] font-medium">Restrictions:</span>
          <label className="flex items-center gap-1.5 text-xs text-[#656d76]">
            Choices (comma-separated)
            <input value={choices} onChange={e => setChoices(e.target.value)} placeholder="none" className={`${inputSm} w-52`} />
          </label>
          <label className="flex items-center gap-1.5 text-xs text-[#656d76]">
            Max length
            <input type="number" step="1" min="1" value={maxLength} onChange={e => setMaxLength(e.target.value)} placeholder="none" className={`${inputSm} w-24`} />
          </label>
        </div>
      )}
      {(dtype === 'file' || dtype === 'file_list') && (
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-xs text-[#656d76] font-medium">Restrictions:</span>
          <label className="flex items-center gap-1.5 text-xs text-[#656d76]">
            Accept
            <input value={accept} onChange={e => setAccept(e.target.value)} placeholder=".csv,.txt" className={`${inputSm} w-36`} />
          </label>
          <label className="flex items-center gap-1.5 text-xs text-[#656d76]">
            Max size (bytes)
            <input type="number" step="1" min="1" value={maxSize} onChange={e => setMaxSize(e.target.value)} placeholder="none" className={`${inputSm} w-28`} />
          </label>
        </div>
      )}
      {(dtype === 'date' || dtype === 'datetime') && (
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-xs text-[#656d76] font-medium">Restrictions:</span>
          <label className="flex items-center gap-1.5 text-xs text-[#656d76]">
            Not before
            <input type={dtype === 'date' ? 'date' : 'datetime-local'} value={minDate} onChange={e => setMinDate(e.target.value)} className={inputSm} />
          </label>
          <label className="flex items-center gap-1.5 text-xs text-[#656d76]">
            Not after
            <input type={dtype === 'date' ? 'date' : 'datetime-local'} value={maxDate} onChange={e => setMaxDate(e.target.value)} className={inputSm} />
          </label>
        </div>
      )}
      {updateField.error && <span className="text-xs text-[#d1242f]">{String(updateField.error)}</span>}
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

  // Fetch by UUID — name changes don't affect the URL
  const { data: schema, isLoading, error } = useSchema(id!)
  const { data: allSchemas } = useSchemas()
  const updateField = useUpdateField(schema?.name ?? '')
  const deleteField = useDeleteField(schema?.name ?? '')
  const deleteSchema = useDeleteSchema()
  const updateSchema = useUpdateSchema(schema?.name ?? '')
  const [editingField, setEditingField] = useState<string | null>(null)
  const [confirmDeleteField, setConfirmDeleteField] = useState<string | null>(null)

  function setDisplayField(fieldName: string | null) {
    updateSchema.mutate({ display_field: fieldName })
  }

  if (isLoading) return <LoadingState />
  if (error || !schema) return <ErrorState message={error ? String(error) : 'Schema not found'} />

  const parentSchema = schema.parent_id
    ? allSchemas?.find(s => s.id === schema.parent_id)
    : null

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-1.5 text-sm text-[#656d76]">
        <Link to="/schemas" className="hover:text-[#0969da]">Schemas</Link>
        <span>/</span>
        <span className="text-[#1f2328] font-medium">{schema.name}</span>
      </nav>

      {/* Header */}
      <div>
        {editing ? (
          <MetaEditor schema={schema} onDone={() => setEditing(false)} />
        ) : (
          <div className="flex items-start justify-between">
            <div>
              <h1 className="text-xl font-semibold text-[#1f2328]">{schema.name}</h1>
              <p className="mt-0.5 text-sm text-[#656d76]">
                {schema.description ?? <span className="italic">No description</span>}
              </p>
              {parentSchema && (
                <p className="mt-1 text-sm text-[#656d76]">
                  Inherits from{' '}
                  <Link to={`/schemas/${parentSchema.id}`} className="text-[#0969da] hover:underline">
                    {parentSchema.name}
                  </Link>
                </p>
              )}
            </div>
            <Button size="sm" onClick={() => setEditing(true)}>Edit</Button>
          </div>
        )}
      </div>

      {/* Fields */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-base font-semibold text-[#1f2328]">
            Fields
            <span className="ml-2 text-sm font-normal text-[#656d76]">
              {schema.fields.length} own
            </span>
          </h2>
          {!addingField && (
            <Button size="sm" onClick={() => setAddingField(true)}>+ Add field</Button>
          )}
        </div>

        <Table>
          <Thead>
            <tr>
              <Th>Name</Th>
              <Th>Type</Th>
              <Th>Required</Th>
              <Th className="w-20" />
            </tr>
          </Thead>
          <Tbody>
            {schema.fields.length === 0 && !addingField && (
              <Tr><td colSpan={4} className="px-4 py-3 text-sm text-[#656d76] italic">No fields yet.</td></Tr>
            )}
            {schema.fields.map(field => (
              editingField === field.name ? (
                <Tr key={field.id}>
                  <td colSpan={4} className="p-0">
                    <FieldEditForm
                      field={field}
                      schemaName={schema.name}
                      onDone={() => setEditingField(null)}
                    />
                  </td>
                </Tr>
              ) : (
                <Tr key={field.id}>
                  <Td>
                    <span className="flex items-center gap-1.5">
                      <span className="font-mono text-sm">{field.name}</span>
                      {schema.display_field === field.name && (
                        <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-[#fff8c5] text-[#9a6700] border border-[#d4a72c55]" title="Display field — used as record name">
                          display
                        </span>
                      )}
                    </span>
                  </Td>
                  <Td>
                    <div className="flex flex-col gap-0.5">
                      <div className="flex items-center gap-1.5">
                        <Badge variant="accent">{field.type}</Badge>
                        {field.type === 'reference' && !!field.restrictions?.schema && (
                          <span className="text-xs text-[#656d76]">
                            {'→ '}
                            <Link
                              to={`/schemas/${allSchemas?.find(s => s.name === String(field.restrictions.schema))?.id ?? String(field.restrictions.schema)}`}
                              className="text-[#0969da] hover:underline"
                            >
                              {String(field.restrictions.schema)}
                            </Link>
                          </span>
                        )}
                      </div>
                      <RestrictionsSummary restrictions={field.restrictions} type={field.type} />
                    </div>
                  </Td>
                  <Td>
                    <button
                      onClick={() => updateField.mutate({ fieldName: field.name, required: !field.required })}
                      className={`text-xs font-medium px-2 py-0.5 rounded-full border cursor-pointer transition-colors ${
                        field.required
                          ? 'bg-[#dafbe1] text-[#1a7f37] border-[#4ac26b66] hover:bg-[#aceebb]'
                          : 'bg-[#f6f8fa] text-[#656d76] border-[#d0d7de] hover:bg-[#eff2f5]'
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
                            onClick={() => deleteField.mutate(field.name, { onSuccess: () => setConfirmDeleteField(null) })}
                            disabled={deleteField.isPending}
                            className="text-xs text-[#d1242f] font-medium hover:underline disabled:opacity-50"
                          >
                            Confirm
                          </button>
                          <button
                            onClick={() => setConfirmDeleteField(null)}
                            className="text-xs text-[#656d76] hover:underline"
                          >
                            Cancel
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            onClick={() => setDisplayField(schema.display_field === field.name ? null : field.name)}
                            className={`text-xs transition-colors ${schema.display_field === field.name ? 'text-[#9a6700]' : 'text-[#d0d7de] hover:text-[#9a6700]'}`}
                            title={schema.display_field === field.name ? 'Clear display field' : 'Set as display field'}
                          >
                            ★
                          </button>
                          <button
                            onClick={() => { setConfirmDeleteField(null); setEditingField(field.name) }}
                            className="text-xs text-[#656d76] hover:text-[#0969da] transition-colors"
                            title="Edit field"
                          >
                            ✎
                          </button>
                          <button
                            onClick={() => { setEditingField(null); setConfirmDeleteField(field.name) }}
                            className="text-xs text-[#656d76] hover:text-[#d1242f] transition-colors"
                            title="Remove field"
                          >
                            ✕
                          </button>
                        </>
                      )}
                    </span>
                  </Td>
                </Tr>
              )
            ))}
          </Tbody>
          {addingField && (
            <tfoot>
              <tr>
                <td colSpan={4} className="p-0">
                  <AddFieldForm schemaName={schema.name} onDone={() => setAddingField(false)} />
                </td>
              </tr>
            </tfoot>
          )}
        </Table>
      </div>

      {/* Danger zone */}
      <div className="border border-[#d1242f33] rounded-md">
        <div className="px-4 py-3 border-b border-[#d1242f33] bg-[#ffebe9] rounded-t-md">
          <h2 className="text-sm font-semibold text-[#d1242f]">Danger zone</h2>
        </div>
        <div className="px-4 py-3 flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-[#1f2328]">Delete this schema</p>
            <p className="text-xs text-[#656d76]">This cannot be undone. All field definitions will be removed.</p>
          </div>
          {confirmDelete ? (
            <div className="flex items-center gap-2">
              <span className="text-xs text-[#656d76]">Are you sure?</span>
              <Button variant="danger" size="sm" onClick={() => deleteSchema.mutate(schema.name, { onSuccess: () => navigate('/schemas') })} disabled={deleteSchema.isPending}>
                {deleteSchema.isPending ? 'Deleting…' : 'Confirm delete'}
              </Button>
              <Button size="sm" onClick={() => setConfirmDelete(false)}>Cancel</Button>
            </div>
          ) : (
            <Button variant="danger" size="sm" onClick={() => setConfirmDelete(true)}>
              Delete schema
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}
