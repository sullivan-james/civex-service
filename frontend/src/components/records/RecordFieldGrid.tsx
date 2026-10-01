import { useEffect, useRef, useState, type ReactNode } from 'react'
import { filesApi } from '../../api/files'
import type { Field } from '../../api/schemas'
import { formatBytes, toInputProps } from '../../utils/restrictions'
import { displayLabel } from '../../utils/naming'
import { isGeometry, parseLocation, type Geometry } from '../../utils/geo'
import { LocatorMap } from '../ui/LocatorMap'
import { tidy, toFieldUnit } from '../../utils/units'
import { Button, Checkbox, FormError } from '../ui'
import { Paperclip, X } from '../ui/icons'
import { DynamicField, type FileRef } from './DynamicField'
import { PendingFiles, type StagedFile } from './PendingFiles'
import { acceptProblem, sizeProblem } from '../../utils/fileChecks'
import { ReferenceChips } from './ReferenceChips'
import type { FieldSaveError } from './saveErrors'
import { FieldValue } from './FieldValue'

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

/** Attach / replace / remove for file and file_list fields. An upload starts
 * as soon as a file is picked, but the file only waits beside the field
 * until someone approves it: the record changes (and any workflow that
 * watches the field runs) on approval, never on upload. Pending files live
 * in the page, so leaving it discards them. */
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
  const inputRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [staged, setStaged] = useState<StagedFile[]>([])
  const { accept, maxSize } = toInputProps(field)

  async function pick(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? [])
    e.target.value = ''
    if (!files.length) return
    const tooBig = files.find((f) => maxSize !== undefined && f.size > maxSize)
    if (tooBig) {
      setError(`${tooBig.name} is too large — max ${formatBytes(maxSize!)}`)
      return
    }
    setError(null)
    try {
      const uploaded: StagedFile[] = []
      for (let i = 0; i < files.length; i++) {
        setBusy(
          files.length > 1
            ? `Uploading ${i + 1} of ${files.length}…`
            : 'Uploading…',
        )
        const ref = await filesApi.uploadStreaming(files[i], () => {})
        uploaded.push({
          ref,
          problem:
            acceptProblem(files[i].name, files[i].type, accept) ??
            sizeProblem(files[i].size, maxSize),
        })
      }
      // A single-file field holds one pending file: a new pick replaces it.
      setStaged((prev) => (multiple ? [...prev, ...uploaded] : uploaded))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setBusy(null)
    }
  }

  function approve() {
    const approved = staged.map((s) => s.ref)
    setStaged([])
    onSave(multiple ? [...refs, ...approved] : approved[0])
  }

  const remove = (sha256: string) => {
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
          <a
            href={`/api/files/${ref.sha256}?filename=${encodeURIComponent(ref.resolved_filename ?? ref.filename)}`}
            download={ref.resolved_filename ?? ref.filename}
            className="truncate text-accent hover:underline"
            title={`Download · ${(ref.size / 1024).toFixed(1)} KB`}
          >
            {ref.resolved_filename ?? ref.filename}
          </a>
          <span className="shrink-0 text-xs text-fg-muted">
            {(ref.size / 1024).toFixed(1)} KB
          </span>
          <button
            type="button"
            onClick={() => remove(ref.sha256)}
            aria-label={`Remove ${ref.filename}`}
            className="shrink-0 rounded p-1 text-fg-muted hover:bg-canvas-inset hover:text-danger cursor-pointer"
          >
            <X size={12} />
          </button>
        </div>
      ))}
      <PendingFiles
        staged={staged}
        replacing={!multiple && refs.length ? refs[0].filename : undefined}
        onDiscard={(sha) =>
          setStaged((p) => p.filter((s) => s.ref.sha256 !== sha))
        }
        onApprove={approve}
        onDiscardAll={() => setStaged([])}
      />
      <div className="flex flex-wrap items-center gap-2">
        {refs.length === 0 && staged.length === 0 && (
          <span className="inline-flex items-center rounded-full bg-attention-subtle px-3 py-1 text-xs font-semibold text-attention-emphasis">
            empty
          </span>
        )}
        <input
          ref={inputRef}
          type="file"
          multiple={multiple}
          accept={accept}
          onChange={pick}
          className="hidden"
          aria-label={`Upload ${displayLabel(field.name, field.label)}`}
        />
        <Button
          size="sm"
          disabled={busy !== null}
          onClick={() => inputRef.current?.click()}
        >
          {busy ??
            (multiple
              ? 'Add files…'
              : refs.length
                ? 'Replace file…'
                : 'Attach file…')}
        </Button>
      </div>
      {error && (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
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
                    <button
                      type="button"
                      onClick={onDismissError}
                      aria-label="Dismiss error"
                      className="shrink-0 rounded p-1 text-danger hover:bg-canvas/50 cursor-pointer"
                    >
                      <X size={12} />
                    </button>
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
