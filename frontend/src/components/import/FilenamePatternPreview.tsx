import { Field, Input } from '../ui'
import { ArrowRight } from '../ui/icons'
import {
  FILENAME_FORMAT_TOKENS_HELP,
  extractCaptureGroup,
  normalizeNumericKey,
  parseFilenameByTokenFormat,
} from '../../utils/filenamePattern'

export type ExtractOutputType =
  'string' | 'integer' | 'float' | 'date' | 'datetime'

export interface FilenameExtraction {
  filename: string
  /** Raw captured text, or null if the pattern didn't match. */
  extracted: string | null
  /** `extracted` converted to `outputType`, or null if extraction/conversion failed. */
  value: string | number | null
  error: string | null
}

/** Apply `pattern` (and, for date/datetime, `dateFormat`) to one filename —
 * the single source of truth both the live preview table and the wizard's
 * confirm/run steps use, so what you see previewed is exactly what gets
 * written. */
export function extractFromFilename(
  filename: string,
  pattern: string,
  outputType: ExtractOutputType,
  dateFormat: string,
): FilenameExtraction {
  const { value: extracted, error } = extractCaptureGroup(filename, pattern)
  if (error || extracted === null) {
    return { filename, extracted: null, value: null, error }
  }
  if (outputType === 'integer') {
    const n = parseInt(normalizeNumericKey(extracted), 10)
    return isNaN(n)
      ? { filename, extracted, value: null, error: 'Cannot parse as integer' }
      : { filename, extracted, value: n, error: null }
  }
  if (outputType === 'float') {
    const n = parseFloat(extracted)
    return isNaN(n)
      ? { filename, extracted, value: null, error: 'Cannot parse as float' }
      : { filename, extracted, value: n, error: null }
  }
  if (outputType === 'date' || outputType === 'datetime') {
    if (!dateFormat) {
      return { filename, extracted, value: null, error: 'Date format required' }
    }
    const iso = parseFilenameByTokenFormat(extracted, dateFormat)
    if (!iso) {
      return {
        filename,
        extracted,
        value: null,
        error: `Format didn't match "${extracted}"`,
      }
    }
    return { filename, extracted, value: iso, error: null }
  }
  return { filename, extracted, value: extracted, error: null }
}

interface Props {
  filenames: string[]
  pattern: string
  onPatternChange: (pattern: string) => void
  outputType: ExtractOutputType
  dateFormat: string
  onDateFormatChange: (format: string) => void
  maxRows?: number
}

/** Regex pattern input + live extraction preview against real, currently
 * selected filenames — the piece that makes the `extract_from_filename` /
 * `match_files_to_records` token format usable without trial-and-error
 * round trips through a saved workflow run. */
export function FilenamePatternPreview({
  filenames,
  pattern,
  onPatternChange,
  outputType,
  dateFormat,
  onDateFormatChange,
  maxRows = 8,
}: Props) {
  const isDate = outputType === 'date' || outputType === 'datetime'
  const preview = filenames
    .slice(0, maxRows)
    .map((f) => extractFromFilename(f, pattern, outputType, dateFormat))
  const matchCount = filenames.filter(
    (f) =>
      extractFromFilename(f, pattern, outputType, dateFormat).error === null,
  ).length

  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <Field label="Filename pattern" span={isDate ? 6 : 12}>
          <Input
            size="sm"
            value={pattern}
            onChange={(e) => onPatternChange(e.target.value)}
            placeholder="Regex — use a capture group ( ) to select the key"
            className="w-full font-mono"
          />
        </Field>
        {isDate && (
          <Field label="Date format" span={6}>
            <Input
              size="sm"
              value={dateFormat}
              onChange={(e) => onDateFormatChange(e.target.value)}
              placeholder={`e.g. YYYYMMDD-HHmmSS (tokens: ${FILENAME_FORMAT_TOKENS_HELP})`}
              className="w-full font-mono"
            />
          </Field>
        )}
      </div>

      {pattern && (
        <div className="border border-border rounded-md overflow-hidden">
          <table className="w-full text-xs">
            <tbody>
              {preview.map((row) => (
                <tr
                  key={row.filename}
                  className="border-t border-border-muted first:border-t-0"
                >
                  <td className="px-2 py-1.5 font-mono text-fg-muted truncate max-w-[16rem]">
                    {row.filename}
                  </td>
                  <td className="px-2 py-1.5 text-fg-subtle">
                    <ArrowRight size={11} className="inline" />
                  </td>
                  <td className="px-2 py-1.5">
                    {row.error ? (
                      <span className="text-danger">{row.error}</span>
                    ) : (
                      <code className="bg-success-subtle border border-success-muted px-1.5 py-0.5 rounded-md text-success">
                        {String(row.value)}
                      </code>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="px-2 py-1.5 text-xs text-fg-muted bg-canvas-subtle border-t border-border-muted">
            {matchCount} of {filenames.length} filename
            {filenames.length === 1 ? '' : 's'} match
            {filenames.length > maxRows && ` (showing first ${maxRows} below)`}
          </div>
        </div>
      )}
    </div>
  )
}
