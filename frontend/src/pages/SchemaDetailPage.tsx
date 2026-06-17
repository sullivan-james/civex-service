import { useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useSchema, useUpdateSchema, useAddField, useUpdateField, useDeleteSchema, useSchemas } from '../hooks/useSchemas'
import {
  Button, Badge,
  Table, Thead, Th, Tbody, Tr, Td,
  LoadingState, ErrorState,
} from '../components/ui'

const FIELD_TYPES = ['string', 'integer', 'float', 'boolean', 'file', 'reference']

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

// --- Add field form ---

function AddFieldForm({ schemaName, onDone }: { schemaName: string; onDone: () => void }) {
  const [fieldName, setFieldName] = useState('')
  const [type, setType] = useState('string')
  const [required, setRequired] = useState(false)
  const [refSchema, setRefSchema] = useState('')
  const addField = useAddField(schemaName)
  const { data: allSchemas } = useSchemas()

  const canAdd = !!fieldName.trim() && (type !== 'reference' || !!refSchema)

  function handleAdd() {
    if (!canAdd) return
    const restrictions = type === 'reference' ? { schema: refSchema } : undefined
    addField.mutate(
      { name: fieldName.trim(), type, required, restrictions },
      { onSuccess: () => { setFieldName(''); setType('string'); setRequired(false); setRefSchema(''); onDone() } },
    )
  }

  return (
    <div className="border-t border-[#d0d7de] bg-[#f6f8fa] px-4 py-3 flex items-center gap-3 flex-wrap">
      <input
        value={fieldName}
        onChange={e => setFieldName(e.target.value)}
        onKeyDown={e => e.key === 'Enter' && handleAdd()}
        placeholder="Field name"
        autoFocus
        className="border border-[#d0d7de] rounded-md px-3 py-1.5 text-sm bg-white w-40 focus:outline-none focus:border-[#0969da] focus:ring-1 focus:ring-[#0969da]"
      />
      <select
        value={type}
        onChange={e => { setType(e.target.value); setRefSchema('') }}
        className="border border-[#d0d7de] rounded-md px-2 py-1.5 text-sm bg-white focus:outline-none focus:border-[#0969da]"
      >
        {FIELD_TYPES.map(t => <option key={t}>{t}</option>)}
      </select>
      {type === 'reference' && (
        <select
          value={refSchema}
          onChange={e => setRefSchema(e.target.value)}
          className="border border-[#d0d7de] rounded-md px-2 py-1.5 text-sm bg-white focus:outline-none focus:border-[#0969da]"
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
      {addField.error && <span className="text-xs text-[#d1242f]">{String(addField.error)}</span>}
      <div className="flex gap-2 ml-auto">
        <Button variant="primary" size="sm" onClick={handleAdd} disabled={addField.isPending || !canAdd}>
          {addField.isPending ? 'Adding…' : 'Add field'}
        </Button>
        <Button size="sm" onClick={onDone}>Cancel</Button>
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

  // Fetch by UUID — name changes don't affect the URL
  const { data: schema, isLoading, error } = useSchema(id!)
  const { data: allSchemas } = useSchemas()
  const updateField = useUpdateField(schema?.name ?? '')
  const deleteSchema = useDeleteSchema()

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
            </tr>
          </Thead>
          <Tbody>
            {schema.fields.length === 0 && !addingField && (
              <Tr><Td className="text-[#656d76] italic">No fields yet.</Td></Tr>
            )}
            {schema.fields.map(field => (
              <Tr key={field.id}>
                <Td><span className="font-mono text-sm">{field.name}</span></Td>
                <Td>
                  <Badge variant="accent">{field.type}</Badge>
                  {field.type === 'reference' && field.restrictions?.schema && (
                    <span className="ml-1.5 text-xs text-[#656d76]">
                      {'→ '}
                      <Link
                        to={`/schemas/${allSchemas?.find(s => s.name === field.restrictions.schema)?.id ?? field.restrictions.schema}`}
                        className="text-[#0969da] hover:underline"
                      >
                        {field.restrictions.schema}
                      </Link>
                    </span>
                  )}
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
              </Tr>
            ))}
          </Tbody>
          {addingField && (
            <tfoot>
              <tr>
                <td colSpan={3} className="p-0">
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
