import { useState } from 'react'
import type { Schema } from '../../api/schemas'
import type { FileRef } from './DynamicField'
import { useRecords } from '../../hooks/useRecords'
import { Button, Badge, Field, Input, Select, FormError } from '../ui'
import { ArrowUp, ArrowRight, ScanText } from '../ui/icons'
import { DynamicField } from './DynamicField'
import { RecordSearchPicker } from './RecordSearchPicker'
import { datetimeLocalToUTC } from '../../utils/dates'
import { displayLabel } from '../../utils/naming'
import { errorMessage } from '../../lib/errors'
import { fieldErrorInfo } from '../../utils/validationErrors'
import {
  FILENAME_FORMAT_TOKENS_HELP,
  parseFilenameByTokenFormat,
} from '../../utils/filenamePattern'

interface Props {
  schemas: Schema[]
  datasetName: string
  onSubmit: (
    schemaName: string,
    data: Record<string, unknown>,
    parentRecordId?: string,
  ) => void
  onCancel: () => void
  isPending?: boolean
  /** Raw mutation error — parsed into per-field messages against `schema.fields`. */
  error?: unknown
  selectableSchemaIds?: string[]
  lockedParentRecordId?: string
}

// ── Filename extraction helpers ────────────────────────────────────────────

const FORMAT_HELP = FILENAME_FORMAT_TOKENS_HELP
const parseByFormat = parseFilenameByTokenFormat

interface FileSource {
  filename: string
  label: string
}

function collectFileSources(
  values: Record<string, unknown>,
  fields: Schema['fields'],
): FileSource[] {
  const out: FileSource[] = []
  for (const f of fields) {
    if (f.type === 'file') {
      const ref = values[f.name] as FileRef | undefined
      if (ref?.filename)
        out.push({
          filename: ref.filename,
          label: `${ref.filename} (${displayLabel(f.name, f.label)})`,
        })
    } else if (f.type === 'file_list') {
      const refs = values[f.name] as FileRef[] | undefined
      for (const ref of refs ?? []) {
        if (ref?.filename)
          out.push({
            filename: ref.filename,
            label: `${ref.filename} (${displayLabel(f.name, f.label)})`,
          })
      }
    }
  }
  return out
}

// ── FilenameExtractor component ────────────────────────────────────────────

interface ExtractorProps {
  sources: FileSource[]
  fieldType: string
  onApply: (value: unknown) => void
  onClose: () => void
}

function FilenameExtractor({
  sources,
  fieldType,
  onApply,
  onClose,
}: ExtractorProps) {
  const [source, setSource] = useState(sources[0]?.filename ?? '')
  const [pattern, setPattern] = useState('')
  const [fmt, setFmt] = useState('')
  const [extracted, setExtracted] = useState<string | null>(null)
  const [converted, setConverted] = useState<unknown>(undefined)
  const [patternErr, setPatternErr] = useState<string | null>(null)
  const [convertErr, setConvertErr] = useState<string | null>(null)

  const isDate = fieldType === 'date' || fieldType === 'datetime'

  function run() {
    setExtracted(null)
    setConverted(undefined)
    setPatternErr(null)
    setConvertErr(null)
    if (!pattern) return
    let raw: string
    try {
      const m = new RegExp(pattern).exec(source)
      if (!m) {
        setPatternErr('No match in filename')
        return
      }
      raw = m[1] ?? m[0] // prefer first capture group
    } catch (e) {
      setPatternErr('Invalid regex: ' + (e as Error).message)
      return
    }
    setExtracted(raw)

    // Convert to the target field type
    if (fieldType === 'integer') {
      const n = parseInt(raw, 10)
      if (isNaN(n)) {
        setConvertErr('Cannot parse as integer')
        return
      }
      setConverted(n)
    } else if (fieldType === 'float') {
      const n = parseFloat(raw)
      if (isNaN(n)) {
        setConvertErr('Cannot parse as float')
        return
      }
      setConverted(n)
    } else if (fieldType === 'date') {
      const isoStr = fmt ? parseByFormat(raw, fmt) : raw
      if (!isoStr) {
        setConvertErr(`Cannot parse "${raw}" with format "${fmt}"`)
        return
      }
      // Validate
      if (isNaN(new Date(isoStr + 'T00:00:00Z').getTime())) {
        setConvertErr('Result is not a valid date')
        return
      }
      setConverted(isoStr)
    } else if (fieldType === 'datetime') {
      const isoStr = fmt ? parseByFormat(raw, fmt) : raw
      if (!isoStr) {
        setConvertErr(`Cannot parse "${raw}" with format "${fmt}"`)
        return
      }
      const d = new Date(isoStr)
      if (isNaN(d.getTime())) {
        setConvertErr('Result is not a valid datetime')
        return
      }
      // datetimeLocalToUTC treats the string as local time if tz-naive
      setConverted(datetimeLocalToUTC(isoStr.slice(0, 16))) // store as UTC
    } else {
      // string
      setConverted(raw)
    }
  }

  function apply() {
    if (converted === undefined) return
    onApply(converted)
    onClose()
  }

  const hasResult = extracted !== null && !patternErr && !convertErr

  return (
    <div className="mt-2 border border-accent-subtle-border rounded-md bg-accent-subtle p-3 space-y-2">
      {/* File source */}
      {sources.length > 1 ? (
        <Field label="File source" hideLabel>
          <Select
            size="sm"
            value={source}
            onChange={(e) => {
              setSource(e.target.value)
              setExtracted(null)
              setConverted(undefined)
            }}
            className="w-full"
          >
            {sources.map((s) => (
              <option key={s.filename} value={s.filename}>
                {s.label}
              </option>
            ))}
          </Select>
        </Field>
      ) : (
        <code
          className="text-xs text-fg-muted font-mono block truncate"
          title={source}
        >
          {source}
        </code>
      )}

      {/* Regex input */}
      <div className="flex gap-2">
        <Field label="Regex pattern" hideLabel className="flex-1">
          <Input
            size="sm"
            value={pattern}
            onChange={(e) => {
              setPattern(e.target.value)
              setExtracted(null)
              setConverted(undefined)
            }}
            onKeyDown={(e) => e.key === 'Enter' && run()}
            placeholder="Regex — use a capture group ( ) to select the part you want"
            className="w-full font-mono"
          />
        </Field>
        <button
          onClick={run}
          className="px-3 py-2 text-xs rounded-md border border-border bg-canvas hover:bg-canvas-subtle shrink-0"
        >
          Test
        </button>
      </div>

      {/* Date format (date / datetime only) */}
      {isDate && (
        <div className="flex gap-2 items-center">
          <Field label="Date format" hideLabel className="flex-1">
            <Input
              size="sm"
              value={fmt}
              onChange={(e) => {
                setFmt(e.target.value)
                setConverted(undefined)
                setConvertErr(null)
              }}
              onKeyDown={(e) => e.key === 'Enter' && run()}
              placeholder={`Format, e.g. YYYYMMDD-HHmmSS  (tokens: ${FORMAT_HELP})`}
              className="w-full font-mono"
            />
          </Field>
        </div>
      )}

      {/* Errors */}
      {patternErr && (
        <p role="alert" className="text-xs text-danger">
          {patternErr}
        </p>
      )}
      {convertErr && (
        <p role="alert" className="text-xs text-danger">
          {convertErr}
        </p>
      )}

      {/* Preview */}
      {hasResult && (
        <div className="flex items-center gap-2 text-xs flex-wrap">
          <span className="text-fg-muted">Extracted:</span>
          <code className="bg-canvas border border-border px-2 py-1 rounded-md font-mono">
            {extracted}
          </code>
          {converted !== extracted && converted !== undefined && (
            <>
              <ArrowRight size={12} className="text-fg-muted" />
              <code className="bg-success-subtle border border-success-muted px-2 py-1 rounded-md font-mono text-success">
                {String(converted)}
              </code>
            </>
          )}
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-2">
        <button
          onClick={apply}
          disabled={converted === undefined}
          className="px-3 py-2 text-xs font-medium rounded-md border border-accent bg-accent text-fg-on-emphasis hover:bg-accent-emphasis disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Apply
        </button>
        <button
          onClick={onClose}
          className="px-3 py-2 text-xs font-medium rounded-md border border-border bg-canvas hover:bg-canvas-subtle"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

// ── RecordForm ─────────────────────────────────────────────────────────────

const EXTRACTABLE_TYPES = new Set([
  'string',
  'integer',
  'float',
  'date',
  'datetime',
])

export function RecordForm({
  schemas,
  datasetName,
  onSubmit,
  onCancel,
  isPending,
  error,
  selectableSchemaIds,
  lockedParentRecordId,
}: Props) {
  const pickableSchemas = selectableSchemaIds
    ? schemas.filter((s) => selectableSchemaIds.includes(s.id))
    : schemas
  const [selectedSchemaId, setSelectedSchemaId] = useState<string>(
    pickableSchemas[0]?.id ?? '',
  )
  const [parentRecordId, setParentRecordId] = useState<string>('')
  const [values, setValues] = useState<Record<string, unknown>>({})
  const [extractingField, setExtractingField] = useState<string | null>(null)

  const schema = pickableSchemas.find((s) => s.id === selectedSchemaId)
  const parentSchema =
    !lockedParentRecordId && schema?.parent_id
      ? schemas.find((s) => s.id === schema.parent_id)
      : null

  // Only need to know whether *any* parent-schema records exist — the
  // picker itself searches on demand rather than listing every candidate.
  const { data: parentPage } = useRecords(
    datasetName,
    parentSchema ? { schema: parentSchema.name, limit: 1 } : undefined,
  )
  const hasParentCandidates = (parentPage?.total ?? 0) > 0

  function handleSchemaChange(id: string) {
    setSelectedSchemaId(id)
    setParentRecordId('')
    setValues({})
    setExtractingField(null)
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
    onSubmit(
      schema.name,
      data,
      lockedParentRecordId || parentRecordId || undefined,
    )
  }

  if (!schema) return null

  const { fieldErrors, generalMessage, technical } = fieldErrorInfo(
    error,
    schema.fields.map((f) => f.name),
    errorMessage,
  )

  // Collect available file sources from currently-uploaded file fields
  const fileSources = collectFileSources(values, schema.fields)

  return (
    <div className="border border-border rounded-md bg-canvas-subtle p-4 space-y-4">
      {/* Schema selector */}
      <div className="flex flex-col gap-1">
        <span className="text-xs font-semibold text-fg-muted uppercase tracking-wide">
          Schema
        </span>
        <div className="flex flex-wrap gap-2">
          {pickableSchemas.map((s) => (
            <button
              key={s.id}
              onClick={() => handleSchemaChange(s.id)}
              className={`flex items-center gap-2 px-3 py-2 rounded-md text-sm border transition-colors cursor-pointer ${
                s.id === selectedSchemaId
                  ? 'bg-accent text-fg-on-emphasis border-accent'
                  : 'bg-canvas text-fg border-border hover:bg-canvas-inset'
              }`}
            >
              {s.name}
              {s.parent_id && (
                <span className="inline-flex items-center gap-0.5 text-xs opacity-70">
                  <ArrowUp size={11} />
                  {schemas.find((p) => p.id === s.parent_id)?.name}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Parent record selector */}
      {parentSchema &&
        (!hasParentCandidates ? (
          <div className="flex flex-col gap-1">
            <span className="text-xs font-semibold text-fg-muted uppercase tracking-wide">
              Parent record
              <Badge variant="accent" className="ml-2">
                {displayLabel(parentSchema.name, parentSchema.label)}
              </Badge>
            </span>
            <p className="text-xs text-danger">
              No {displayLabel(parentSchema.name, parentSchema.label)} records
              in this dataset yet — add one first.
            </p>
          </div>
        ) : (
          <Field
            label={
              <>
                Parent record
                <Badge variant="accent" className="ml-2">
                  {displayLabel(parentSchema.name, parentSchema.label)}
                </Badge>
              </>
            }
          >
            <RecordSearchPicker
              schemaName={parentSchema.name}
              value={parentRecordId || undefined}
              onChange={(id) => setParentRecordId(id ?? '')}
              placeholder={`Search ${displayLabel(parentSchema.name, parentSchema.label)} records…`}
              className="w-full max-w-sm"
            />
          </Field>
        ))}

      {/* Dynamic fields */}
      {schema.fields.length > 0 && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {schema.fields.map((field) => {
            const canExtract =
              EXTRACTABLE_TYPES.has(field.type) && fileSources.length > 0
            const isExtracting = extractingField === field.name
            return (
              <div
                key={field.id}
                className={isExtracting ? 'sm:col-span-2' : ''}
              >
                <Field
                  label={
                    <span className="flex items-center justify-between gap-2">
                      <span className="flex items-center gap-2">
                        <span title={field.name}>
                          {displayLabel(field.name, field.label)}
                        </span>
                        <Badge variant="accent">{field.type}</Badge>
                        {field.required && (
                          <Badge variant="success">required</Badge>
                        )}
                      </span>
                      {canExtract && (
                        <button
                          onClick={() =>
                            setExtractingField(isExtracting ? null : field.name)
                          }
                          className={`inline-flex items-center gap-1 text-xs px-2 py-2 rounded-md border transition-colors shrink-0 ${
                            isExtracting
                              ? 'border-accent bg-accent-subtle text-accent'
                              : 'border-border text-fg-muted hover:border-accent hover:text-accent'
                          }`}
                          title="Fill this field from an uploaded filename"
                        >
                          <ScanText size={11} /> from filename
                        </button>
                      )}
                    </span>
                  }
                  error={fieldErrors[field.name]}
                >
                  <DynamicField
                    field={field}
                    value={values[field.name]}
                    onChange={(v) =>
                      setValues((prev) => ({ ...prev, [field.name]: v }))
                    }
                  />
                </Field>
                {isExtracting && (
                  <FilenameExtractor
                    sources={fileSources}
                    fieldType={field.type}
                    onApply={(v) =>
                      setValues((prev) => ({ ...prev, [field.name]: v }))
                    }
                    onClose={() => setExtractingField(null)}
                  />
                )}
              </div>
            )
          })}
        </div>
      )}

      <FormError message={generalMessage} technical={technical} />

      <div className="flex gap-2 pt-1">
        <Button
          variant="primary"
          size="sm"
          onClick={handleSubmit}
          disabled={
            isPending ||
            (!!parentSchema && !parentRecordId) ||
            (!!parentSchema && !hasParentCandidates)
          }
        >
          {isPending ? 'Adding…' : 'Add record'}
        </Button>
        <Button size="sm" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  )
}
