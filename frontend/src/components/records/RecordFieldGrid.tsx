import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useUploadCollection } from '../../hooks/uploadCollection'
import { useFileUploads } from '../../hooks/useFileUploads'
import type { Field } from '../../api/schemas'
import { formatBytes, toInputProps } from '../../utils/restrictions'
import { displayLabel } from '../../utils/naming'
import { isGeometry, parseLocation, type Geometry } from '../../utils/geo'
import { LocatorMap } from '../ui/LocatorMap'
import { tidy, toFieldUnit } from '../../utils/units'
import {
  Checkbox,
  ConfirmDialog,
  FileDropZone,
  FormError,
  IconButton,
} from '../ui'
import { Paperclip, X } from '../ui/icons'
import { DynamicField, type FileRef } from './DynamicField'
import { acceptProblem, sizeProblem } from '../../utils/fileChecks'
import { ReferenceChips } from './ReferenceChips'
import type { FieldSaveError } from './saveErrors'
import { FieldValue } from './FieldValue'
import { FileLink, FileLocationChip } from './FileLocation'
import { UploadProgress } from './UploadProgress'

const isEmpty = (v: unknown) =>
  v === null ||
  v === undefined ||
  v === '' ||
  (Array.isArray(v) && v.length === 0)

/** Types whose editor commits the moment a choice is made. Everything else
 * commits when focus leaves the row (or on Enter for single-line inputs). */
const COMMIT_ON_CHANGE = new Set(['enum'])
const COMMIT_ON_ENTER = new Set([
  'string',
  'integer',
  'float',
  'date',
  'datetime',
  'url',
  'tags',
  'geo',
])

function sameValue(a: unknown, b: unknown) {
  return (isEmpty(a) && isEmpty(b)) || JSON.stringify(a) === JSON.stringify(b)
}

/** The draft as the API wants it; `undefined` clears the field, `null`
 * means the draft is unusable and the edit should be dropped. */
function toSaved(field: Field, draft: unknown): unknown | undefined | null {
  if (isEmpty(draft)) return undefined
  if (field.type === 'integer') {
    const n = parseInt(draft as string, 10)
    return Number.isNaN(n) ? null : n
  }
  if (field.type === 'float') {
    const unit = field.restrictions?.unit
    if (typeof unit === 'string' && unit) {
      // "1024 ft" into a metres field: convert, never drop the unit.
      const r = toFieldUnit(String(draft), unit)
      return 'error' in r ? null : parseFloat(tidy(r.value))
    }
    const n = parseFloat(draft as string)
    return Number.isNaN(n) ? null : n
  }
  if (field.type === 'geo' && typeof draft === 'string')
    return parseLocation(draft)
  return draft
}

/** Attach / replace / remove for file and file_list fields. Picking or
 * dropping a file uploads it and saves the record straight away, with live
 * progress, so an upload behaves like any other edit. The only question asked
 * is when a file would go: removing one, or replacing one (which removes the
 * current file). The file's type and size are checked first, so a file the
 * field won't take is refused before anything is uploaded. */
function FileControl({
  field,
  value,
  onSave,
}: {
  field: Field
  value: unknown
  onSave: (value: unknown | undefined) => void
}) {
  const multiple = field.type === 'file_list'
  const refs: FileRef[] = multiple
    ? ((value as FileRef[] | null | undefined) ?? [])
    : value
      ? [value as FileRef]
      : []
  const [error, setError] = useState<string | null>(null)
  // A file waiting on "are you sure": one to remove, or a replacement to swap in.
  const [removing, setRemoving] = useState<FileRef | null>(null)
  const [replacement, setReplacement] = useState<File | null>(null)
  const collectionId = useUploadCollection()
  const { current, uploading, run, cancel } = useFileUploads(collectionId)
  const { accept, maxSize } = toInputProps(field)
  const label = displayLabel(field.name, field.label)

  async function attach(files: File[]) {
    setError(null)
    for (const f of files) {
      const problem =
        acceptProblem(f.name, f.type, accept) ?? sizeProblem(f.size, maxSize)
      if (problem) {
        setError(`${f.name}: ${problem}`)
        return
      }
    }
    try {
      // Files that finished before a cancel are kept.
      const { refs: done } = await run(files)
      if (done.length) onSave(multiple ? [...refs, ...done] : done[0])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed')
    }
  }

  function pick(files: File[]) {
    // Replacing removes the current file, so that one is confirmed.
    if (!multiple && refs.length) setReplacement(files[0])
    else void attach(files)
  }

  function remove(sha256: string) {
    const rest = refs.filter((r) => r.sha256 !== sha256)
    onSave(multiple ? rest : undefined)
  }

  return (
    <div className="space-y-2">
      {refs.map((ref) => (
        <div
          key={ref.sha256}
          className="flex items-center gap-2 text-sm text-fg"
        >
          <Paperclip size={14} className="shrink-0 text-fg-muted" />
          <FileLink
            file={ref}
            className="truncate text-accent hover:underline"
            title={`Download · ${(ref.size / 1024).toFixed(1)} KB`}
          >
            {ref.resolved_filename ?? ref.filename}
          </FileLink>
          <span className="shrink-0 text-xs text-fg-muted">
            {(ref.size / 1024).toFixed(1)} KB
          </span>
          <FileLocationChip file={ref} />
          <IconButton
            icon={X}
            variant="danger"
            onClick={() => setRemoving(ref)}
            aria-label={`Remove ${ref.filename}`}
          />
        </div>
      ))}
      {refs.length === 0 && (
        <span className="inline-flex items-center rounded-full bg-attention-subtle px-3 py-1 text-xs font-semibold text-attention-emphasis">
          empty
        </span>
      )}
      <FileDropZone
        multiple={multiple}
        accept={accept}
        disabled={uploading}
        inputLabel={`Upload ${label}`}
        onFiles={pick}
      >
        {multiple ? undefined : refs.length ? (
          <span>
            Drop a file here or <span className="text-accent">browse</span> to
            replace it
          </span>
        ) : undefined}
      </FileDropZone>
      {current && <UploadProgress state={current} onCancel={cancel} />}
      {error && (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      )}

      {removing && (
        <ConfirmDialog
          title="Remove file"
          confirmLabel="Remove file"
          variant="danger"
          body={
            <p className="text-sm">
              Remove{' '}
              <strong>{removing.resolved_filename ?? removing.filename}</strong>{' '}
              from this record? The file stays in storage until it is cleaned
              up, but nothing on the record will point to it.
            </p>
          }
          onConfirm={() => {
            remove(removing.sha256)
            setRemoving(null)
          }}
          onClose={() => setRemoving(null)}
        />
      )}
      {replacement && refs[0] && (
        <ConfirmDialog
          title="Replace file"
          confirmLabel="Replace file"
          variant="danger"
          body={
            <p className="text-sm">
              Replace{' '}
              <strong>{refs[0].resolved_filename ?? refs[0].filename}</strong>{' '}
              with <strong>{replacement.name}</strong>? The current file is
              removed from this record.
            </p>
          }
          onConfirm={() => {
            const file = replacement
            setReplacement(null)
            void attach([file])
          }}
          onClose={() => setReplacement(null)}
        />
      )}
    </div>
  )
}

/** One field's value; click it to edit in place. */
function EditableValue({
  field,
  value,
  referenceLabels,
  referenceCollections,
  onSave,
}: {
  field: Field
  value: unknown
  referenceLabels?: Record<string, string | null> | null
  referenceCollections?: Record<string, string> | null
  onSave: (value: unknown | undefined) => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<unknown>(value)
  const editor = useRef<HTMLDivElement>(null)
  const done = useRef(false)

  useEffect(() => {
    if (!editing) return
    editor.current
      ?.querySelector<HTMLElement>('input:not([type=hidden]),select,textarea')
      ?.focus()
  }, [editing])

  function start() {
    done.current = false
    setDraft(value)
    setEditing(true)
  }
  function finish(next: unknown = draft) {
    if (done.current) return
    done.current = true
    setEditing(false)
    const saved = toSaved(field, next)
    if (saved === null || sameValue(saved, value)) return
    onSave(saved)
  }
  function cancel() {
    done.current = true
    setEditing(false)
  }

  if (field.type === 'file' || field.type === 'file_list')
    return <FileControl field={field} value={value} onSave={onSave} />

  if (field.type === 'reference' || field.type === 'reference_list')
    return (
      <ReferenceChips
        field={field}
        value={value}
        labels={referenceLabels}
        collections={referenceCollections}
        onSave={onSave}
      />
    )

  if (field.type === 'boolean')
    return (
      <label className="inline-flex items-center gap-2 cursor-pointer">
        <Checkbox
          checked={value === true}
          aria-label={displayLabel(field.name, field.label)}
          onChange={(e) => onSave(e.target.checked)}
        />
        <span className="text-fg">{String(value === true)}</span>
      </label>
    )

  if (editing)
    return (
      <div
        ref={editor}
        onBlur={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget)) finish()
        }}
        onKeyDown={(e) => {
          if (e.key === 'Escape') cancel()
          else if (
            e.key === 'Enter' &&
            COMMIT_ON_ENTER.has(field.type) &&
            !(field.type === 'string' && e.target instanceof HTMLSelectElement)
          ) {
            e.preventDefault()
            finish()
          }
        }}
      >
        <DynamicField
          field={field}
          value={draft}
          onChange={(v) => {
            setDraft(v)
            const choice =
              COMMIT_ON_CHANGE.has(field.type) ||
              (field.type === 'string' && toInputProps(field).choices?.length)
            if (choice) finish(v)
          }}
          aria-invalid={undefined}
        />
      </div>
    )

  return (
    <div
      role="button"
      tabIndex={0}
      title="Click to edit"
      onClick={(e) => {
        if ((e.target as HTMLElement).closest('a,button')) return
        start()
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter' && e.target === e.currentTarget) start()
      }}
      className="-mx-2 min-h-8 rounded-md px-2 py-1 cursor-text hover:bg-canvas-inset focus-visible:bg-canvas-inset"
    >
      <FieldValue
        value={value}
        field={field}
        referenceLabels={referenceLabels}
        referenceCollections={referenceCollections}
      />
    </div>
  )
}

/** What the schema demands of a field, as short phrases: "0–100", "≤ 5 MB". */
export function restrictionHints(field: Field): string[] {
  const r = (field.restrictions ?? {}) as Record<string, unknown>
  const hints: string[] = []
  const range = (lo: unknown, hi: unknown, from = '≥', to = '≤') => {
    if (lo !== undefined && hi !== undefined) hints.push(`${lo} – ${hi}`)
    else if (lo !== undefined) hints.push(`${from} ${lo}`)
    else if (hi !== undefined) hints.push(`${to} ${hi}`)
  }
  const day = (v: unknown) => String(v).slice(0, 10)
  switch (field.type) {
    case 'integer':
    case 'float':
      range(r.min, r.max)
      if (typeof r.unit === 'string' && r.unit) hints.push(`in ${r.unit}`)
      break
    case 'geo':
      if (Array.isArray(r.geometry_types) && r.geometry_types.length)
        hints.push((r.geometry_types as string[]).join(', '))
      if (Array.isArray(r.bbox)) hints.push('limited area')
      break
    case 'date':
    case 'datetime':
      range(
        r.min !== undefined ? day(r.min) : undefined,
        r.max !== undefined ? day(r.max) : undefined,
        'from',
        'until',
      )
      break
    case 'string':
    case 'enum':
    case 'longtext':
      if (Array.isArray(r.choices) && r.choices.length)
        hints.push(`one of ${(r.choices as string[]).join(', ')}`)
      if (r.max_length !== undefined) hints.push(`≤ ${r.max_length} chars`)
      break
    case 'file':
    case 'file_list':
      if (r.accept) hints.push(`${r.accept}`)
      if (r.max_size !== undefined)
        hints.push(`≤ ${formatBytes(Number(r.max_size))}`)
      break
    case 'reference':
    case 'reference_list':
      if (typeof r.schema === 'string') hints.push(`→ ${r.schema}`)
      break
  }
  return hints
}

/** A record's field values as plain rows -- label left, value right -- where
 * clicking a value edits just that field and saves it on Enter or when focus
 * moves away (Escape cancels). File fields have attach / replace / remove
 * buttons instead. */
export function RecordFieldGrid({
  fields,
  data,
  referenceLabels,
  referenceCollections,
  onSave,
  errors,
  onDismissError,
  extra,
}: {
  fields: Field[]
  data: Record<string, unknown>
  referenceLabels?: Record<string, string | null> | null
  referenceCollections?: Record<string, string> | null
  /** `undefined` clears the field. */
  onSave: (name: string, value: unknown | undefined) => void
  /** Why the last save of a field failed, shown right under that field. */
  errors?: Record<string, FieldSaveError>
  onDismissError?: () => void
  /** Extra content under a field's value (e.g. the filename extractor). */
  extra?: (field: Field) => ReactNode
}) {
  return (
    <dl className="grid grid-cols-[minmax(8rem,14rem)_1fr] items-start gap-x-6 gap-y-3">
      {fields.map((field) => {
        const numeric = field.type === 'integer' || field.type === 'float'
        const hints = restrictionHints(field)
        return (
          <div key={field.name} className="contents">
            <dt className="pt-1" title={`${field.name} (${field.type})`}>
              <span className="text-fg-muted">
                {displayLabel(field.name, field.label)}
              </span>
              {field.required && (
                <span
                  className="ml-1 text-attention"
                  title="Required"
                  aria-label="required"
                >
                  *
                </span>
              )}
              {hints.length > 0 && (
                <span className="block text-xs text-fg-subtle">
                  {hints.join(' · ')}
                </span>
              )}
            </dt>
            <dd
              className={`min-w-0 break-words text-fg ${numeric ? 'font-mono' : ''}`}
            >
              <EditableValue
                field={field}
                value={data[field.name]}
                referenceLabels={referenceLabels}
                referenceCollections={referenceCollections}
                onSave={(v) => onSave(field.name, v)}
              />
              {field.type === 'geo' && isGeometry(data[field.name]) && (
                <LocatorMap
                  bbox={
                    Array.isArray(field.restrictions?.bbox)
                      ? (field.restrictions.bbox as number[])
                      : null
                  }
                  location={data[field.name] as Geometry}
                  className="mt-2 max-w-xs"
                />
              )}
              {extra?.(field)}
              {errors?.[field.name] && (
                <div className="mt-1 flex items-start gap-2 rounded-md border border-danger-subtle-border bg-danger-subtle px-3 py-2">
                  <div className="min-w-0 flex-1 font-sans">
                    <FormError
                      message={errors[field.name].message}
                      technical={errors[field.name].technical}
                    />
                  </div>
                  {onDismissError && (
                    <IconButton
                      icon={X}
                      variant="danger"
                      onClick={onDismissError}
                      aria-label="Dismiss error"
                    />
                  )}
                </div>
              )}
            </dd>
          </div>
        )
      })}
    </dl>
  )
}
