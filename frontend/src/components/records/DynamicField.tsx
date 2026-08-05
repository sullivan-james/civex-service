import { useState, useEffect, useRef } from 'react'
import { api } from '../../api/client'
import { recordsApi, type CivexRecord } from '../../api/records'
import type { Field } from '../../api/schemas'
import { utcToDatetimeLocal, datetimeLocalToUTC } from '../../utils/dates'
import { Input, Select, Checkbox } from '../ui'

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

function fileAccept(
  restrictions: Record<string, unknown> | undefined,
): string | undefined {
  const acc = restrictions?.accept
  return typeof acc === 'string' ? acc : undefined
}

function fileMaxSize(
  restrictions: Record<string, unknown> | undefined,
): number | undefined {
  const ms = restrictions?.max_size
  return ms !== undefined ? Number(ms) : undefined
}

function validateFileSize(
  file: File,
  maxSize: number | undefined,
): string | null {
  if (maxSize !== undefined && file.size > maxSize) {
    const limit =
      maxSize >= 1_048_576
        ? `${(maxSize / 1_048_576).toFixed(1)} MB`
        : maxSize >= 1024
          ? `${(maxSize / 1024).toFixed(0)} KB`
          : `${maxSize} B`
    return `File too large (${(file.size / 1024).toFixed(0)} KB) — max ${limit}`
  }
  return null
}

function FileField({ field, value, onChange }: Props) {
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const ref = value as FileRef | null | undefined
  const accept = fileAccept(field.restrictions)
  const maxSize = fileMaxSize(field.restrictions)

  async function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    const sizeErr = validateFileSize(file, maxSize)
    if (sizeErr) {
      setError(sizeErr)
      return
    }
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
        <div className="flex items-center gap-2 text-xs text-fg-muted">
          <span>📎 {ref.filename}</span>
          <span>({(ref.size / 1024).toFixed(1)} KB)</span>
          <a
            href={`/api/files/${ref.sha256}`}
            download={ref.filename}
            className="text-accent hover:underline"
          >
            Download
          </a>
        </div>
      )}
      <input
        type="file"
        accept={accept}
        onChange={handleChange}
        disabled={uploading}
        className="block w-full text-sm text-fg file:mr-3 file:py-1 file:px-3 file:rounded file:border-0 file:text-xs file:bg-canvas-subtle file:text-fg hover:file:bg-border-muted cursor-pointer disabled:opacity-50"
      />
      {uploading && <p className="text-xs text-fg-muted">Uploading…</p>}
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  )
}

function FileListField({ field, value, onChange }: Props) {
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const existing = (value as FileRef[] | null | undefined) ?? []
  const accept = fileAccept(field.restrictions)
  const maxSize = fileMaxSize(field.restrictions)

  async function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? [])
    if (!files.length) return
    for (const file of files) {
      const sizeErr = validateFileSize(file, maxSize)
      if (sizeErr) {
        setError(sizeErr)
        return
      }
    }
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
    onChange(existing.filter((r) => r.sha256 !== sha256))
  }

  return (
    <div className="space-y-1.5">
      {existing.map((ref) => (
        <div
          key={ref.sha256}
          className="flex items-center gap-2 text-xs text-fg-muted"
        >
          <span className="truncate">
            {ref.filename} ({(ref.size / 1024).toFixed(1)} KB)
          </span>
          <button
            type="button"
            onClick={() => remove(ref.sha256)}
            className="text-danger hover:underline shrink-0"
          >
            ✕
          </button>
        </div>
      ))}
      <input
        type="file"
        multiple
        accept={accept}
        onChange={handleChange}
        disabled={uploading}
        className="block w-full text-sm text-fg file:mr-3 file:py-1 file:px-3 file:rounded file:border-0 file:text-xs file:bg-canvas-subtle file:text-fg hover:file:bg-border-muted cursor-pointer disabled:opacity-50"
      />
      {uploading && <p className="text-xs text-fg-muted">Uploading…</p>}
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  )
}

function ReferenceField({ field, value, onChange }: Props) {
  const targetSchema = String(field.restrictions?.schema ?? '')
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
        const records = await recordsApi.searchBySchema(
          targetSchema,
          search || undefined,
        )
        setResults(records)
      } finally {
        setLoading(false)
      }
    }, 250)
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
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
    return record.natural_name ?? record.id.slice(0, 8)
  }

  return (
    <div className="relative">
      <Input
        type="text"
        value={
          selectedId
            ? results.find((r) => r.id === selectedId)
              ? labelFor(results.find((r) => r.id === selectedId)!)
              : selectedId.slice(0, 8)
            : search
        }
        onChange={(e) => {
          setSearch(e.target.value)
          onChange(undefined)
          setOpen(true)
        }}
        onFocus={handleFocus}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder={
          targetSchema ? `Search ${targetSchema} records…` : 'Record ID'
        }
        className="w-full"
      />
      {open && (
        <div className="absolute z-10 mt-1 w-full bg-white border border-border rounded-md shadow-sm max-h-48 overflow-y-auto text-sm">
          {loading && <div className="px-3 py-2 text-fg-muted">Loading…</div>}
          {!loading && results.length === 0 && (
            <div className="px-3 py-2 text-fg-muted italic">
              No records found
            </div>
          )}
          {results.map((record) => (
            <button
              key={record.id}
              onMouseDown={() => handleSelect(record)}
              className="w-full text-left px-3 py-1.5 hover:bg-canvas-subtle truncate"
            >
              <span className="font-mono text-xs text-fg-muted">
                {record.id.slice(0, 8)}
              </span>
              {record.natural_name && (
                <span className="ml-2 text-fg">{record.natural_name}</span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export function DynamicField({ field, value, onChange }: Props) {
  switch (field.type) {
    case 'string': {
      const choices = field.restrictions?.choices
      if (Array.isArray(choices) && choices.length) {
        return (
          <Select
            value={(value as string) ?? ''}
            onChange={(e) => onChange(e.target.value)}
            className="w-full"
          >
            {!field.required && <option value="">— optional —</option>}
            {(choices as string[]).map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </Select>
        )
      }
      const maxLength =
        field.restrictions?.max_length !== undefined
          ? Number(field.restrictions.max_length)
          : undefined
      return (
        <Input
          type="text"
          value={(value as string) ?? ''}
          onChange={(e) => onChange(e.target.value)}
          placeholder={field.required ? 'Required' : 'Optional'}
          maxLength={maxLength}
          className="w-full"
        />
      )
    }

    case 'integer': {
      const rMin =
        field.restrictions?.min !== undefined
          ? Number(field.restrictions.min)
          : undefined
      const rMax =
        field.restrictions?.max !== undefined
          ? Number(field.restrictions.max)
          : undefined
      return (
        <Input
          type="number"
          step="1"
          min={rMin}
          max={rMax}
          value={(value as string) ?? ''}
          onChange={(e) => onChange(e.target.value)}
          placeholder={field.required ? 'Required' : 'Optional'}
          className="w-full"
        />
      )
    }

    case 'float': {
      const rMin =
        field.restrictions?.min !== undefined
          ? Number(field.restrictions.min)
          : undefined
      const rMax =
        field.restrictions?.max !== undefined
          ? Number(field.restrictions.max)
          : undefined
      return (
        <Input
          type="number"
          step="any"
          min={rMin}
          max={rMax}
          value={(value as string) ?? ''}
          onChange={(e) => onChange(e.target.value)}
          placeholder={field.required ? 'Required' : 'Optional'}
          className="w-full"
        />
      )
    }

    case 'date':
      return (
        <Input
          type="date"
          value={(value as string) ?? ''}
          min={
            field.restrictions?.min !== undefined
              ? String(field.restrictions.min)
              : undefined
          }
          max={
            field.restrictions?.max !== undefined
              ? String(field.restrictions.max)
              : undefined
          }
          onChange={(e) => onChange(e.target.value)}
          className="w-full"
        />
      )

    case 'datetime': {
      const rMin =
        field.restrictions?.min !== undefined
          ? utcToDatetimeLocal(String(field.restrictions.min))
          : undefined
      const rMax =
        field.restrictions?.max !== undefined
          ? utcToDatetimeLocal(String(field.restrictions.max))
          : undefined
      return (
        <Input
          type="datetime-local"
          value={value ? utcToDatetimeLocal(value as string) : ''}
          min={rMin}
          max={rMax}
          onChange={(e) =>
            onChange(e.target.value ? datetimeLocalToUTC(e.target.value) : '')
          }
          className="w-full"
        />
      )
    }

    case 'boolean':
      return (
        <label className="flex items-center gap-2 text-sm text-fg cursor-pointer select-none">
          <Checkbox
            checked={(value as boolean) ?? false}
            onChange={(e) => onChange(e.target.checked)}
          />
          {field.required ? (
            <span>Required</span>
          ) : (
            <span className="text-fg-muted">Optional</span>
          )}
        </label>
      )

    case 'enum': {
      const enumChoices = field.restrictions?.choices
      return (
        <Select
          value={(value as string) ?? ''}
          onChange={(e) => onChange(e.target.value)}
          className="w-full"
        >
          {!field.required && <option value="">— optional —</option>}
          {Array.isArray(enumChoices)
            ? (enumChoices as string[]).map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))
            : null}
        </Select>
      )
    }

    case 'url':
      return (
        <Input
          type="url"
          value={(value as string) ?? ''}
          onChange={(e) => onChange(e.target.value)}
          placeholder={field.required ? 'https://example.com' : 'Optional URL'}
          className="w-full"
        />
      )

    case 'reference_list': {
      const listVal = Array.isArray(value)
        ? (value as string[]).join(', ')
        : ((value as string) ?? '')
      return (
        <Input
          type="text"
          value={listVal}
          onChange={(e) => {
            const raw = e.target.value
            onChange(
              raw
                ? raw
                    .split(',')
                    .map((s) => s.trim())
                    .filter(Boolean)
                : [],
            )
          }}
          placeholder="Record IDs, comma-separated"
          className="w-full"
        />
      )
    }

    case 'tags': {
      const tagsVal = Array.isArray(value)
        ? (value as string[]).join(', ')
        : ((value as string) ?? '')
      return (
        <Input
          type="text"
          value={tagsVal}
          onChange={(e) => {
            const raw = e.target.value
            onChange(
              raw
                ? raw
                    .split(',')
                    .map((s) => s.trim())
                    .filter(Boolean)
                : [],
            )
          }}
          placeholder="Tags, comma-separated"
          className="w-full"
        />
      )
    }

    case 'file':
      return <FileField field={field} value={value} onChange={onChange} />

    case 'reference':
      return <ReferenceField field={field} value={value} onChange={onChange} />

    case 'file_list':
      return <FileListField field={field} value={value} onChange={onChange} />

    default:
      return (
        <Input
          type="text"
          value={(value as string) ?? ''}
          onChange={(e) => onChange(e.target.value)}
          className="w-full"
        />
      )
  }
}
