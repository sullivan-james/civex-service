import { useState, useEffect, useRef } from 'react'
import { api } from '../../api/client'
import { recordsApi, type CivexRecord } from '../../api/records'
import type { Field } from '../../api/schemas'

export interface FileRef {
  sha256: string
  filename: string
  size: number
}

interface Props {
  field: Field
  value: unknown
  onChange: (value: unknown) => void
}

const inputClass =
  'w-full border border-[#d0d7de] rounded-md px-3 py-1.5 text-sm bg-white focus:outline-none focus:border-[#0969da] focus:ring-1 focus:ring-[#0969da]'

function FileField({ field, value, onChange }: Props) {
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const ref = value as FileRef | null | undefined

  async function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    setError(null)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const result = await api.upload<FileRef>('/files', fd)
      onChange(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="space-y-1">
      {ref && (
        <div className="flex items-center gap-2 text-xs text-[#656d76]">
          <span>📎 {ref.filename}</span>
          <span>({(ref.size / 1024).toFixed(1)} KB)</span>
          <a
            href={`/api/files/${ref.sha256}`}
            download={ref.filename}
            className="text-[#0969da] hover:underline"
          >
            Download
          </a>
        </div>
      )}
      <input
        type="file"
        onChange={handleChange}
        disabled={uploading}
        className="block w-full text-sm text-[#1f2328] file:mr-3 file:py-1 file:px-3 file:rounded file:border-0 file:text-xs file:bg-[#f6f8fa] file:text-[#1f2328] hover:file:bg-[#eaeef2] cursor-pointer disabled:opacity-50"
      />
      {uploading && <p className="text-xs text-[#656d76]">Uploading…</p>}
      {error   && <p className="text-xs text-red-600">{error}</p>}
    </div>
  )
}

function FileListField({ value, onChange }: Props) {
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const existing = (value as FileRef[] | null | undefined) ?? []

  async function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? [])
    if (!files.length) return
    setUploading(true)
    setError(null)
    try {
      const newRefs: FileRef[] = []
      for (const file of files) {
        const fd = new FormData()
        fd.append('file', file)
        const ref = await api.upload<FileRef>('/files', fd)
        newRefs.push(ref)
      }
      onChange([...existing, ...newRefs])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  function remove(sha256: string) {
    onChange(existing.filter(r => r.sha256 !== sha256))
  }

  return (
    <div className="space-y-1.5">
      {existing.map(ref => (
        <div key={ref.sha256} className="flex items-center gap-2 text-xs text-[#656d76]">
          <span className="truncate">{ref.filename} ({(ref.size / 1024).toFixed(1)} KB)</span>
          <button type="button" onClick={() => remove(ref.sha256)} className="text-[#d1242f] hover:underline shrink-0">✕</button>
        </div>
      ))}
      <input
        type="file"
        multiple
        onChange={handleChange}
        disabled={uploading}
        className="block w-full text-sm text-[#1f2328] file:mr-3 file:py-1 file:px-3 file:rounded file:border-0 file:text-xs file:bg-[#f6f8fa] file:text-[#1f2328] hover:file:bg-[#eaeef2] cursor-pointer disabled:opacity-50"
      />
      {uploading && <p className="text-xs text-[#656d76]">Uploading…</p>}
      {error   && <p className="text-xs text-red-600">{error}</p>}
    </div>
  )
}

function ReferenceField({ field, value, onChange }: Props) {
  const targetSchema = field.restrictions?.schema ?? ''
  const [search, setSearch] = useState('')
  const [results, setResults] = useState<CivexRecord[]>([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const selectedId = value as string | undefined

  useEffect(() => {
    if (!targetSchema) return
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(async () => {
      setLoading(true)
      try {
        const records = await recordsApi.searchBySchema(targetSchema, search || undefined)
        setResults(records)
      } finally {
        setLoading(false)
      }
    }, 250)
    return () => { if (timerRef.current) clearTimeout(timerRef.current) }
  }, [search, targetSchema])

  function handleFocus() {
    setOpen(true)
    if (!results.length && targetSchema) {
      recordsApi.searchBySchema(targetSchema).then(setResults)
    }
  }

  function handleSelect(record: CivexRecord) {
    onChange(record.id)
    setOpen(false)
    setSearch('')
  }

  function labelFor(record: CivexRecord) {
    const vals = Object.values(record.data).filter(v => typeof v === 'string' || typeof v === 'number')
    const preview = vals.slice(0, 2).join(' · ')
    return preview ? `${record.id.slice(0, 8)} — ${preview}` : record.id.slice(0, 8)
  }

  return (
    <div className="relative">
      <input
        type="text"
        value={selectedId ? (results.find(r => r.id === selectedId) ? labelFor(results.find(r => r.id === selectedId)!) : selectedId.slice(0, 8)) : search}
        onChange={e => { setSearch(e.target.value); onChange(undefined); setOpen(true) }}
        onFocus={handleFocus}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder={targetSchema ? `Search ${targetSchema} records…` : 'Record ID'}
        className={inputClass}
      />
      {open && (
        <div className="absolute z-10 mt-1 w-full bg-white border border-[#d0d7de] rounded-md shadow-sm max-h-48 overflow-y-auto text-sm">
          {loading && <div className="px-3 py-2 text-[#656d76]">Loading…</div>}
          {!loading && results.length === 0 && (
            <div className="px-3 py-2 text-[#656d76] italic">No records found</div>
          )}
          {results.map(record => (
            <button
              key={record.id}
              onMouseDown={() => handleSelect(record)}
              className="w-full text-left px-3 py-1.5 hover:bg-[#f6f8fa] truncate"
            >
              <span className="font-mono text-xs text-[#656d76]">{record.id.slice(0, 8)}</span>
              {' '}
              <span className="text-[#1f2328]">
                {Object.values(record.data).filter(v => typeof v === 'string' || typeof v === 'number').slice(0, 2).join(' · ')}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export function DynamicField({ field, value, onChange }: Props) {
  switch (field.type) {
    case 'string':
      return (
        <input
          type="text"
          value={(value as string) ?? ''}
          onChange={e => onChange(e.target.value)}
          placeholder={field.required ? 'Required' : 'Optional'}
          className={inputClass}
        />
      )

    case 'integer':
      return (
        <input
          type="number"
          step="1"
          value={(value as string) ?? ''}
          onChange={e => onChange(e.target.value)}
          placeholder={field.required ? 'Required' : 'Optional'}
          className={inputClass}
        />
      )

    case 'float':
      return (
        <input
          type="number"
          step="any"
          value={(value as string) ?? ''}
          onChange={e => onChange(e.target.value)}
          placeholder={field.required ? 'Required' : 'Optional'}
          className={inputClass}
        />
      )

    case 'boolean':
      return (
        <label className="flex items-center gap-2 text-sm text-[#1f2328] cursor-pointer select-none">
          <input
            type="checkbox"
            checked={(value as boolean) ?? false}
            onChange={e => onChange(e.target.checked)}
            className="rounded"
          />
          {field.required
            ? <span>Required</span>
            : <span className="text-[#656d76]">Optional</span>
          }
        </label>
      )

    case 'file':
      return <FileField field={field} value={value} onChange={onChange} />

    case 'reference':
      return <ReferenceField field={field} value={value} onChange={onChange} />

    case 'file_list':
      return <FileListField field={field} value={value} onChange={onChange} />

    default:
      return (
        <input
          type="text"
          value={(value as string) ?? ''}
          onChange={e => onChange(e.target.value)}
          className={inputClass}
        />
      )
  }
}
