import { useState } from 'react'
import { filesApi } from '../../api/files'
import { useUploadCollection } from '../../hooks/uploadCollection'
import type { Field } from '../../api/schemas'
import { utcToZonedLocal, datetimeInputToWire } from '../../utils/dates'
import { useFieldTimeZone } from './timeZoneContext'
import { formatBytes, toInputProps } from '../../utils/restrictions'
import { Button, Checkbox, IconButton, Input, Select } from '../ui'
import { displayLabel } from '../../utils/naming'
import {
  exampleWithUnit,
  parseQuantity,
  tidy,
  toFieldUnit,
} from '../../utils/units'
import {
  describeBbox,
  editableText,
  isGeometry,
  locationProblem,
  parseLocation,
  spokenPoint,
} from '../../utils/geo'
import { LocatorMap } from '../ui/LocatorMap'
import { GeoEditorModal } from '../geo/GeoEditorModal'
import { useMapSettings } from '../../hooks/useMapSettings'
import {
  isValidPartialDate,
  placeholderFor,
  precisionHelp,
  type Precision,
} from '../../utils/partialDates'
import { Paperclip, X } from '../ui/icons'
import {
  RecordSearchPicker,
  MultiRecordSearchPicker,
} from './RecordSearchPicker'

import type { FileRef } from '../../api/files'
import { FileLink, FileLocationChip } from './FileLocation'

export type { FileRef }

interface Props {
  field: Field
  value: unknown
  onChange: (value: unknown) => void
  id?: string
  'aria-describedby'?: string
  'aria-invalid'?: boolean
  /** Overrides the default "Required"/"Optional" hint on text and number
   * inputs, for callers (a filter) where neither word makes sense. */
  placeholder?: string
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
  const collectionId = useUploadCollection()
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
      const result = await filesApi.uploadStreaming(
        file,
        setProgress,
        collectionId,
      )
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
          <FileLink
            file={ref}
            className="text-accent hover:underline"
            whenUnavailable={
              <span className="text-fg-subtle">Unavailable</span>
            }
          >
            Download
          </FileLink>
          <FileLocationChip file={ref} />
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
  const collectionId = useUploadCollection()
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
        const ref = await filesApi.uploadStreaming(
          files[i],
          (fraction) =>
            setProgress({ index: i, total: files.length, fraction }),
          collectionId,
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
          <FileLocationChip file={ref} />
          <IconButton
            icon={X}
            variant="danger"
            onClick={() => remove(ref.sha256)}
            aria-label={`Remove ${ref.filename}`}
          />
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

interface InputBase {
  id?: string
  required: boolean
  'aria-describedby'?: string
  'aria-invalid'?: boolean
}

/** A float stored in a unit. Typing "1024 ft" into a metres field stores the
 * converted number; a bare number is taken as already in the field's unit. */
function UnitInput({
  id,
  required,
  value,
  onChange,
  unit,
  min,
  max,
  'aria-describedby': ariaDescribedby,
  'aria-invalid': ariaInvalid,
}: InputBase & {
  value: unknown
  onChange: (value: unknown) => void
  unit: string
  min?: number
  max?: number
}) {
  // What the person typed, kept while it differs from the stored number.
  const [draft, setDraft] = useState<string | null>(null)
  const shown =
    draft ?? (value === undefined || value === null ? '' : String(value))
  const parsed = shown.trim() === '' ? null : toFieldUnit(shown, unit)
  const typedUnit = parseQuantity(shown)?.unit ?? null
  const error = parsed && 'error' in parsed ? parsed.error : null
  const note =
    parsed && 'value' in parsed && typedUnit && typedUnit !== unit
      ? `= ${tidy(parsed.value)} ${unit}`
      : null
  return (
    <div>
      <div className="flex items-center gap-2">
        <Input
          id={id}
          aria-describedby={ariaDescribedby}
          aria-invalid={ariaInvalid || !!error}
          required={required}
          aria-required={required}
          type="text"
          inputMode="decimal"
          value={shown}
          onChange={(e) => {
            const text = e.target.value
            setDraft(text)
            const r = text.trim() === '' ? null : toFieldUnit(text, unit)
            if (r === null) onChange('')
            else if ('value' in r) onChange(tidy(r.value))
            else onChange(text) // unreadable: kept so the form can say why
          }}
          onBlur={() => setDraft(null)}
          placeholder={required ? 'Required' : 'Optional'}
          className="w-full"
          data-min={min}
          data-max={max}
        />
        <span className="text-sm text-fg-muted">{unit}</span>
      </div>
      <p
        role={error ? 'alert' : undefined}
        className={`mt-1 text-xs ${error ? 'text-danger' : 'text-fg-muted'}`}
      >
        {error ??
          note ??
          `Stored in ${unit}. You can also type a value with its unit, such as ${exampleWithUnit(unit)}, and it is converted.`}
      </p>
    </div>
  )
}

/** A location typed as "latitude, longitude" (or WKT, or GeoJSON). The form
 * value is the GeoJSON object once the text reads as one. Everything a person
 * needs to get it right is shown here: what to type, what it was understood
 * as, whether it breaks the field's rules, and where it falls on a map. */
function GeoInput({
  id,
  required,
  value,
  onChange,
  rules,
  title,
  'aria-describedby': ariaDescribedby,
  'aria-invalid': ariaInvalid,
}: InputBase & {
  value: unknown
  onChange: (value: unknown) => void
  rules: { geometry_types?: unknown; bbox?: unknown }
  title: string
}) {
  const [draft, setDraft] = useState<string | null>(null)
  const [mapOpen, setMapOpen] = useState(false)
  const mapSettings = useMapSettings()
  const stored = isGeometry(value)
    ? editableText(value)
    : typeof value === 'string'
      ? value
      : ''
  const shown = draft ?? stored
  const typed = shown.trim() !== ''
  const parsed = typed ? parseLocation(shown) : null
  const unreadable = typed && parsed === null
  const problem = parsed ? locationProblem(parsed, rules) : null
  const box =
    Array.isArray(rules.bbox) && rules.bbox.length === 4
      ? (rules.bbox as number[])
      : null
  const shapes = Array.isArray(rules.geometry_types)
    ? (rules.geometry_types as string[])
    : []
  const helpId = `${id ?? 'geo'}-help`
  return (
    <div className="space-y-2">
      <div className="flex items-start gap-2">
        <Input
          id={id}
          aria-describedby={[ariaDescribedby, helpId].filter(Boolean).join(' ')}
          aria-invalid={ariaInvalid || unreadable || !!problem}
          required={required}
          aria-required={required}
          type="text"
          value={shown}
          onChange={(e) => {
            const text = e.target.value
            setDraft(text)
            if (text.trim() === '') return onChange('')
            onChange(parseLocation(text) ?? text)
          }}
          onBlur={() => setDraft(null)}
          placeholder="latitude, longitude  e.g. 56.12, -3.41"
          className="w-full font-mono"
        />
        <Button size="sm" onClick={() => setMapOpen(true)} className="shrink-0">
          Edit on map…
        </Button>
      </div>
      {mapOpen && (
        <GeoEditorModal
          title={`Location: ${title}`}
          value={isGeometry(value) ? value : parsed}
          rules={rules}
          map={
            mapSettings
              ? {
                  tileUrl: mapSettings.tile_url,
                  attribution: mapSettings.attribution,
                }
              : undefined
          }
          onClose={() => setMapOpen(false)}
          onApply={(g) => {
            setDraft(null)
            onChange(g ?? '')
            setMapOpen(false)
          }}
        />
      )}
      <div id={helpId} className="space-y-1 text-xs text-fg-muted">
        {!typed && (
          <p>
            Latitude then longitude, in degrees. South and west are negative:{' '}
            <span className="font-mono">56.12, -3.41</span> is 56.12° N, 3.41°
            W.
          </p>
        )}
        {parsed && !problem && spokenPoint(parsed) && (
          <p className="text-success">Reads as {spokenPoint(parsed)}.</p>
        )}
        {unreadable && (
          <p role="alert" className="text-danger">
            Couldn't read that as a location. Use{' '}
            <span className="font-mono">latitude, longitude</span>, for example{' '}
            <span className="font-mono">56.12, -3.41</span>.
          </p>
        )}
        {problem && (
          <p role="alert" className="text-danger">
            {problem}
          </p>
        )}
        {(shapes.length > 0 || box) && (
          <p>
            Allowed:{' '}
            {[
              shapes.length ? shapes.join(' or ') : null,
              box ? `within ${describeBbox(box)}` : null,
            ]
              .filter(Boolean)
              .join(', ')}
            .
          </p>
        )}
        <details>
          <summary className="cursor-pointer select-none hover:text-fg">
            Other ways to enter a location
          </summary>
          <ul className="mt-1 list-disc space-y-0.5 pl-4">
            <li>
              Copy the coordinates from a map app (right-click a point) and
              paste them here.
            </li>
            <li>
              Well-known text, longitude first:{' '}
              <span className="font-mono">POINT(-3.41 56.12)</span>
            </li>
            <li>
              GeoJSON, for lines and areas:{' '}
              <span className="font-mono">
                {'{"type":"Point","coordinates":[-3.41,56.12]}'}
              </span>
            </li>
            <li>
              A depth or height can be added as a third number in GeoJSON.
            </li>
          </ul>
        </details>
      </div>
      {(box || parsed) && (
        <LocatorMap bbox={box} location={parsed} className="max-w-sm" />
      )}
    </div>
  )
}

/** A date that may be a year or a month, when the schema allows it. */
function PartialDateInput({
  id,
  required,
  value,
  onChange,
  precision,
  'aria-describedby': ariaDescribedby,
  'aria-invalid': ariaInvalid,
}: InputBase & {
  value: unknown
  onChange: (value: unknown) => void
  precision: Precision
}) {
  const text = (value as string) ?? ''
  const bad = text.trim() !== '' && !isValidPartialDate(text)
  return (
    <div>
      <Input
        id={id}
        aria-describedby={ariaDescribedby}
        aria-invalid={ariaInvalid || bad}
        required={required}
        aria-required={required}
        type="text"
        value={text}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholderFor(precision)}
        className="w-full"
      />
      <p
        role={bad ? 'alert' : undefined}
        className={`mt-1 text-xs ${bad ? 'text-danger' : 'text-fg-muted'}`}
      >
        {bad
          ? `Not a valid date. Use ${placeholderFor(precision)}.`
          : `${precisionHelp(precision)} Stored exactly as you write it.`}
      </p>
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
  placeholder,
}: Props) {
  const timeZone = useFieldTimeZone(field)
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
          placeholder={
            placeholder ?? (field.required ? 'Required' : 'Optional')
          }
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
          placeholder={
            placeholder ?? (field.required ? 'Required' : 'Optional')
          }
          className="w-full"
        />
      )
    }

    case 'float': {
      const { min: rMin, max: rMax, unit } = toInputProps(field)
      if (unit)
        return (
          <UnitInput
            id={id}
            aria-describedby={ariaDescribedby}
            aria-invalid={ariaInvalid}
            required={field.required}
            value={value}
            onChange={onChange}
            unit={unit}
            min={rMin}
            max={rMax}
          />
        )
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
          placeholder={
            placeholder ?? (field.required ? 'Required' : 'Optional')
          }
          className="w-full"
        />
      )
    }

    case 'geo':
      return (
        <GeoInput
          id={id}
          aria-describedby={ariaDescribedby}
          aria-invalid={ariaInvalid}
          required={field.required}
          value={value}
          onChange={onChange}
          rules={field.restrictions ?? {}}
          title={displayLabel(field.name, field.label)}
        />
      )

    case 'date': {
      const { minDate, maxDate, precision } = toInputProps(field)
      // The browser's date picker can only produce full dates.
      if (precision && precision !== 'day')
        return (
          <PartialDateInput
            id={id}
            aria-describedby={ariaDescribedby}
            aria-invalid={ariaInvalid}
            required={field.required}
            value={value}
            onChange={onChange}
            precision={precision}
          />
        )
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
      const { minDate: rMin, maxDate: rMax } = toInputProps(field, timeZone)
      return (
        <div>
          <Input
            id={id}
            aria-describedby={ariaDescribedby}
            aria-invalid={ariaInvalid}
            required={field.required}
            aria-required={field.required}
            type="datetime-local"
            value={value ? utcToZonedLocal(value as string, timeZone) : ''}
            min={rMin}
            max={rMax}
            onChange={(e) =>
              onChange(
                e.target.value
                  ? datetimeInputToWire(e.target.value, timeZone)
                  : '',
              )
            }
            className="w-full"
          />
          {timeZone && (
            <p className="mt-1 text-xs text-fg-muted">Time in {timeZone}</p>
          )}
        </div>
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
          placeholder={
            placeholder ??
            (field.required ? 'https://example.com' : 'Optional URL')
          }
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
