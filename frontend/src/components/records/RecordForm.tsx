import { useState } from 'react'
import type { Schema } from '../../api/schemas'
import { useRecords } from '../../hooks/useRecords'
import { Button, Badge } from '../ui'
import { DynamicField } from './DynamicField'

interface Props {
  schemas: Schema[]
  datasetName: string
  onSubmit: (schemaName: string, data: Record<string, unknown>, parentRecordId?: string) => void
  onCancel: () => void
  isPending?: boolean
  error?: string | null
}

function recordSummary(data: Record<string, unknown>, schema: Schema): string {
  const parts = schema.fields
    .filter(f => f.type !== 'file' && f.type !== 'boolean')
    .slice(0, 2)
    .map(f => data[f.name])
    .filter(v => v !== undefined && v !== '')
  return parts.length ? parts.join(' · ') : ''
}

export function RecordForm({ schemas, datasetName, onSubmit, onCancel, isPending, error }: Props) {
  const [selectedSchemaId, setSelectedSchemaId] = useState<string>(schemas[0]?.id ?? '')
  const [parentRecordId, setParentRecordId] = useState<string>('')
  const [values, setValues] = useState<Record<string, unknown>>({})

  const schema = schemas.find(s => s.id === selectedSchemaId)
  const parentSchema = schema?.parent_id ? schemas.find(s => s.id === schema.parent_id) : null

  // Fetch parent candidates lazily — only runs when a child schema is selected
  const { data: parentPage } = useRecords(
    datasetName,
    parentSchema ? { schema: parentSchema.name, limit: 200 } : undefined,
  )
  const parentCandidates = parentPage?.items ?? []

  function handleSchemaChange(id: string) {
    setSelectedSchemaId(id)
    setParentRecordId('')
    setValues({})
  }

  function coerce(value: unknown, type: string): unknown {
    if (value === '' || value === undefined || value === null) return undefined
    if (type === 'integer') return parseInt(value as string, 10)
    if (type === 'float') return parseFloat(value as string)
    return value
  }

  function handleSubmit() {
    if (!schema) return
    const data: Record<string, unknown> = {}
    for (const field of schema.fields) {
      const coerced = coerce(values[field.name], field.type)
      if (coerced !== undefined) data[field.name] = coerced
    }
    onSubmit(schema.name, data, parentRecordId || undefined)
  }

  if (!schema) return null

  return (
    <div className="border border-[#d0d7de] rounded-md bg-[#f6f8fa] p-4 space-y-4">

      {/* Schema selector */}
      <div className="flex flex-col gap-1">
        <label className="text-xs font-semibold text-[#656d76] uppercase tracking-wide">Schema</label>
        <div className="flex flex-wrap gap-2">
          {schemas.map(s => (
            <button
              key={s.id}
              onClick={() => handleSchemaChange(s.id)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm border transition-colors cursor-pointer ${
                s.id === selectedSchemaId
                  ? 'bg-[#0969da] text-white border-[#0969da]'
                  : 'bg-white text-[#1f2328] border-[#d0d7de] hover:bg-[#eff2f5]'
              }`}
            >
              {s.name}
              {s.parent_id && (
                <span className="text-xs opacity-70">
                  ↑ {schemas.find(p => p.id === s.parent_id)?.name}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Parent record selector — only fetched when needed */}
      {parentSchema && (
        <div className="flex flex-col gap-1">
          <label className="text-xs font-semibold text-[#656d76] uppercase tracking-wide">
            Parent record
            <Badge variant="accent" className="ml-1.5">{parentSchema.name}</Badge>
          </label>
          {parentCandidates.length === 0 ? (
            <p className="text-xs text-[#d1242f]">
              No {parentSchema.name} records in this dataset yet — add one first.
            </p>
          ) : (
            <select
              value={parentRecordId}
              onChange={e => setParentRecordId(e.target.value)}
              className="border border-[#d0d7de] rounded-md px-3 py-1.5 text-sm bg-white focus:outline-none focus:border-[#0969da] w-full max-w-sm"
            >
              <option value="">— Select a {parentSchema.name} record —</option>
              {parentCandidates.map(r => {
                const label = recordSummary(r.data, parentSchema)
                return (
                  <option key={r.id} value={r.id}>
                    {label ? `${label} (${r.id.slice(0, 8)})` : r.id.slice(0, 8)}
                  </option>
                )
              })}
            </select>
          )}
        </div>
      )}

      {/* Dynamic fields */}
      {schema.fields.length > 0 && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {schema.fields.map(field => (
            <div key={field.id} className="flex flex-col gap-1">
              <label className="text-xs font-medium text-[#1f2328] flex items-center gap-1.5">
                <span className="font-mono">{field.name}</span>
                <Badge variant="accent">{field.type}</Badge>
                {field.required && <Badge variant="success">required</Badge>}
              </label>
              <DynamicField
                field={field}
                value={values[field.name]}
                onChange={v => setValues(prev => ({ ...prev, [field.name]: v }))}
              />
            </div>
          ))}
        </div>
      )}

      {error && <p className="text-xs text-[#d1242f]">{error}</p>}

      <div className="flex gap-2 pt-1">
        <Button
          variant="primary"
          size="sm"
          onClick={handleSubmit}
          disabled={
            isPending ||
            (!!parentSchema && !parentRecordId) ||
            (!!parentSchema && parentCandidates.length === 0)
          }
        >
          {isPending ? 'Adding…' : 'Add record'}
        </Button>
        <Button size="sm" onClick={onCancel}>Cancel</Button>
      </div>
    </div>
  )
}
