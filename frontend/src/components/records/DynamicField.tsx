import { useState } from 'react'
import { filesApi } from '../../api/files'
import type { Field } from '../../api/schemas'
import { utcToDatetimeLocal, datetimeLocalToUTC } from '../../utils/dates'
import { formatBytes, toInputProps } from '../../utils/restrictions'
import { Input, Select, Checkbox } from '../ui'
import { Paperclip, X } from '../ui/icons'
import {
  RecordSearchPicker,
  MultiRecordSearchPicker,
} from './RecordSearchPicker'

export interface FileRef {
  sha256: string
  filename: string
  size: number
  resolved_filename?: string
}

interface Props {
  field: Field
  value: unknown
  onChange: (value: unknown) => void
  id?: string
  'aria-describedby'?: string
  'aria-invalid'?: boolean
}

function validateFileSize(
  file: File,
  maxSize: number | undefined,
): string | null {
  if (maxSize !== undefined && file.size > maxSize) {
    return `File too large (${(file.size / 1024).toFixed(0)} KB) — max ${formatBytes(maxSize)}`
  }
  return null
}

/** `label` overrides the percentage text, e.g. "Uploading 2 of 3… 45%" for a
 * multi-file batch. */
function UploadProgress({
  fraction,
  label,
}: {
  fraction: number
  label?: string
}) {
  const pct = Math.round(fraction * 100)
  return (
    <div className="space-y-1">
      <div className="h-1.5 w-full bg-border-muted rounded-full overflow-hidden">
        <div
          className="h-full bg-accent transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="text-xs text-fg-muted">{label ?? `Uploading… ${pct}%`}</p>
    </div>
  )
}

function FileField({
  field,
  value,
  onChange,
  id,
  'aria-describedby': ariaDescribedby,
  'aria-invalid': ariaInvalid,
}: Props) {
  const [uploading, setUploading] = useState(false)
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const ref = value as FileRef | null | undefined
  const { accept, maxSize } = toInputProps(field)

  async function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    const sizeErr = validateFileSize(file, maxSize)
    if (sizeErr) {
      setError(sizeErr)
      return
    }
    setUploading(true)
    setProgress(0)
    setError(null)
    try {
      const result = await filesApi.uploadStreaming(file, setProgress)
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
          <span
            className="inline-flex items-center gap-1"
            title={
              ref.resolved_filename && ref.resolved_filename !== ref.filename
                ? `Original: ${ref.filename}`
                : undefined
            }
          >
            <Paperclip size={12} /> {ref.resolved_filename ?? ref.filename}
          </span>
          <span>({(ref.size / 1024).toFixed(1)} KB)</span>
          <a
            href={`/api/files/${ref.sha256}`}
            download={ref.resolved_filename ?? ref.filename}
            className="text-accent hover:underline"
          >
            Download
          </a>
        </div>
      )}
      <input
        id={id}
        aria-describedby={ariaDescribedby}
        aria-invalid={ariaInvalid}
        required={field.required && !ref}
        aria-required={field.required}
        type="file"
        accept={accept}
        onChange={handleChange}
        disabled={uploading}
        className="block w-full text-sm text-fg file:mr-3 file:py-2 file:px-3 file:rounded-md file:border-0 file:text-xs file:bg-canvas-subtle file:text-fg hover:file:bg-border-muted cursor-pointer disabled:opacity-50"
      />
      {uploading && <UploadProgress fraction={progress} />}
      {error && (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      )}
    </div>
  )
}

function FileListField({
  field,
  value,
  onChange,
  id,
  'aria-describedby': ariaDescribedby,
  'aria-invalid': ariaInvalid,
}: Props) {
  const [uploading, setUploading] = useState(false)
  const [progress, setProgress] = useState<{
    index: number
    total: number
    fraction: number
  } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const existing = (value as FileRef[] | null | undefined) ?? []
  const { accept, maxSize } = toInputProps(field)

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
      for (let i = 0; i < files.length; i++) {
        const ref = await filesApi.uploadStreaming(files[i], (fraction) =>
          setProgress({ index: i, total: files.length, fraction }),
        )
        newRefs.push(ref)
      }
      onChange([...existing, ...newRefs])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setUploading(false)
      setProgress(null)
    }
  }

  function remove(sha256: string) {
    onChange(existing.filter((r) => r.sha256 !== sha256))
  }

  return (
    <div className="space-y-2">
      {existing.map((ref) => (
        <div
          key={ref.sha256}
          className="flex items-center gap-2 text-xs text-fg-muted"
        >
          <span
            className="truncate"
            title={
              ref.resolved_filename && ref.resolved_filename !== ref.filename
                ? `Original: ${ref.filename}`
                : undefined
            }
          >
            {ref.resolved_filename ?? ref.filename} (
            {(ref.size / 1024).toFixed(1)} KB)
          </span>
          <button
            type="button"
            onClick={() => remove(ref.sha256)}
            className="text-danger hover:underline shrink-0"
          >
            <X size={12} />
          </button>
        </div>
      ))}
      <input
        id={id}
        aria-describedby={ariaDescribedby}
        aria-invalid={ariaInvalid}
        required={field.required && existing.length === 0}
        aria-required={field.required}
        type="file"
        multiple
        accept={accept}
        onChange={handleChange}
        disabled={uploading}
        className="block w-full text-sm text-fg file:mr-3 file:py-2 file:px-3 file:rounded-md file:border-0 file:text-xs file:bg-canvas-subtle file:text-fg hover:file:bg-border-muted cursor-pointer disabled:opacity-50"
      />
      {uploading && progress && (
        <UploadProgress
          fraction={progress.fraction}
          label={
            progress.total > 1
              ? `Uploading ${progress.index + 1} of ${progress.total}… ${Math.round(progress.fraction * 100)}%`
              : undefined
          }
        />
      )}
      {error && (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      )}
    </div>
  )
}

export function DynamicField({
  field,
  value,
  onChange,
  id,
  'aria-describedby': ariaDescribedby,
  'aria-invalid': ariaInvalid,
}: Props) {
  switch (field.type) {
    case 'string': {
      const { choices, maxLength } = toInputProps(field)
      if (choices && choices.length) {
        return (
          <Select
            id={id}
            aria-describedby={ariaDescribedby}
            aria-invalid={ariaInvalid}
            required={field.required}
            aria-required={field.required}
            value={(value as string) ?? ''}
            onChange={(e) => onChange(e.target.value)}
            className="w-full"
          >
            {!field.required && <option value="">— optional —</option>}
            {choices.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </Select>
        )
      }
      return (
        <Input
          id={id}
          aria-describedby={ariaDescribedby}
          aria-invalid={ariaInvalid}
          required={field.required}
          aria-required={field.required}
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
      const { min: rMin, max: rMax } = toInputProps(field)
      return (
        <Input
          id={id}
          aria-describedby={ariaDescribedby}
          aria-invalid={ariaInvalid}
          required={field.required}
          aria-required={field.required}
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
      const { min: rMin, max: rMax } = toInputProps(field)
      return (
        <Input
          id={id}
          aria-describedby={ariaDescribedby}
          aria-invalid={ariaInvalid}
          required={field.required}
          aria-required={field.required}
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

    case 'date': {
      const { minDate, maxDate } = toInputProps(field)
      return (
        <Input
          id={id}
          aria-describedby={ariaDescribedby}
          aria-invalid={ariaInvalid}
          required={field.required}
          aria-required={field.required}
          type="date"
          value={(value as string) ?? ''}
          min={minDate}
          max={maxDate}
          onChange={(e) => onChange(e.target.value)}
          className="w-full"
        />
      )
    }

    case 'datetime': {
      const { minDate: rMin, maxDate: rMax } = toInputProps(field)
      return (
        <Input
          id={id}
          aria-describedby={ariaDescribedby}
          aria-invalid={ariaInvalid}
          required={field.required}
          aria-required={field.required}
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
        <label
          htmlFor={id}
          className="flex items-center gap-2 text-sm text-fg cursor-pointer select-none"
        >
          <Checkbox
            id={id}
            aria-describedby={ariaDescribedby}
            aria-invalid={ariaInvalid}
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
      const { choices: enumChoices } = toInputProps(field)
      return (
        <Select
          id={id}
          aria-describedby={ariaDescribedby}
          aria-invalid={ariaInvalid}
          required={field.required}
          aria-required={field.required}
          value={(value as string) ?? ''}
          onChange={(e) => onChange(e.target.value)}
          className="w-full"
        >
          {!field.required && <option value="">— optional —</option>}
          {enumChoices?.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </Select>
      )
    }

    case 'url':
      return (
        <Input
          id={id}
          aria-describedby={ariaDescribedby}
          aria-invalid={ariaInvalid}
          required={field.required}
          aria-required={field.required}
          type="url"
          value={(value as string) ?? ''}
          onChange={(e) => onChange(e.target.value)}
          placeholder={field.required ? 'https://example.com' : 'Optional URL'}
          className="w-full"
        />
      )

    case 'reference_list': {
      const targetSchema = toInputProps(field).targetSchema ?? ''
      const listVal = Array.isArray(value) ? (value as string[]) : []
      return (
        <MultiRecordSearchPicker
          schemaName={targetSchema}
          value={listVal}
          onChange={onChange}
          id={id}
          aria-describedby={ariaDescribedby}
          aria-invalid={ariaInvalid}
        />
      )
    }

    case 'tags': {
      const tagsVal = Array.isArray(value)
        ? (value as string[]).join(', ')
        : ((value as string) ?? '')
      return (
        <Input
          id={id}
          aria-describedby={ariaDescribedby}
          aria-invalid={ariaInvalid}
          required={field.required}
          aria-required={field.required}
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
      return (
        <FileField
          field={field}
          value={value}
          onChange={onChange}
          id={id}
          aria-describedby={ariaDescribedby}
          aria-invalid={ariaInvalid}
        />
      )

    case 'reference': {
      const targetSchema = toInputProps(field).targetSchema ?? ''
      return (
        <RecordSearchPicker
          schemaName={targetSchema}
          value={value as string | undefined}
          onChange={onChange}
          id={id}
          aria-describedby={ariaDescribedby}
          aria-invalid={ariaInvalid}
          required={field.required}
          placeholder={
            targetSchema ? `Search ${targetSchema} records…` : 'Record ID'
          }
        />
      )
    }

    case 'file_list':
      return (
        <FileListField
          field={field}
          value={value}
          onChange={onChange}
          id={id}
          aria-describedby={ariaDescribedby}
          aria-invalid={ariaInvalid}
        />
      )

    default:
      return (
        <Input
          id={id}
          aria-describedby={ariaDescribedby}
          aria-invalid={ariaInvalid}
          required={field.required}
          aria-required={field.required}
          type="text"
          value={(value as string) ?? ''}
          onChange={(e) => onChange(e.target.value)}
          className="w-full"
        />
      )
  }
}
