import { useState } from 'react'
import { api } from '../../api/client'
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
