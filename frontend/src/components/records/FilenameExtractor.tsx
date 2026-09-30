import { useState } from 'react'
import type { Field as SchemaField } from '../../api/schemas'
import type { FileRef } from './DynamicField'
import { Field, Input, Select } from '../ui'
import { ArrowRight } from '../ui/icons'
import { datetimeLocalToUTC } from '../../utils/dates'
import { displayLabel } from '../../utils/naming'
import {
  FILENAME_FORMAT_TOKENS_HELP,
  parseFilenameByTokenFormat,
} from '../../utils/filenamePattern'

// ── Filename extraction helpers ────────────────────────────────────────────

const FORMAT_HELP = FILENAME_FORMAT_TOKENS_HELP
const parseByFormat = parseFilenameByTokenFormat

export interface FileSource {
  filename: string
  label: string
}

export function collectFileSources(
  values: Record<string, unknown>,
  fields: SchemaField[],
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

export function FilenameExtractor({
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

/** Field types a value can be pulled out of a filename for. */
export const EXTRACTABLE_TYPES = new Set([
  'string',
  'integer',
  'float',
  'date',
  'datetime',
])
