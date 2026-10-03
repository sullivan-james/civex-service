/**
 * Name templates — the frontend half of `civex/domain/templating.py`.
 *
 * A template is literal text with `{name}` or `{name:spec}` variables (`{{`
 * and `}}` are literal braces). The server owns validation and rendering; this
 * file only reads a template well enough to edit it (find variables, change a
 * variable's format, insert at the cursor) and never throws on bad input, so
 * half-typed text still works.
 */

export interface TemplateVariable {
  /** Text between the braces, e.g. `taken_on:YYYY-MM`. */
  raw: string
  name: string
  spec: string | null
  /** Offsets of the whole `{...}` in the template. */
  start: number
  end: number
}

/** Variables in order of appearance. Skips escaped braces and unclosed ones. */
export function variablesIn(template: string): TemplateVariable[] {
  const found: TemplateVariable[] = []
  let i = 0
  while (i < template.length) {
    const ch = template[i]
    if (ch === '{' && template[i + 1] === '{') {
      i += 2
    } else if (ch === '{') {
      const close = template.indexOf('}', i + 1)
      if (close === -1) break
      const raw = template.slice(i + 1, close)
      const colon = raw.indexOf(':')
      found.push({
        raw,
        name: (colon === -1 ? raw : raw.slice(0, colon)).trim(),
        spec: colon === -1 ? null : raw.slice(colon + 1).trim() || null,
        start: i,
        end: close + 1,
      })
      i = close + 1
    } else {
      i += 1
    }
  }
  return found
}

/** `template` with the format of its `index`th variable replaced (null removes it). */
export function setVariableFormat(
  template: string,
  index: number,
  spec: string | null,
): string {
  const v = variablesIn(template)[index]
  if (!v) return template
  const next = `{${v.name}${spec ? `:${spec}` : ''}}`
  return template.slice(0, v.start) + next + template.slice(v.end)
}

/** `snippet` written over the selection; returns the new text and cursor. */
export function insertAt(
  template: string,
  selectionStart: number,
  selectionEnd: number,
  snippet: string,
): { value: string; cursor: number } {
  const start = Math.min(selectionStart, selectionEnd)
  const end = Math.max(selectionStart, selectionEnd)
  return {
    value: template.slice(0, start) + snippet + template.slice(end),
    cursor: start + snippet.length,
  }
}

export interface FormatChoice {
  /** Written after the colon; null means no format. */
  spec: string | null
  label: string
}

const NONE: FormatChoice = { spec: null, label: 'As entered' }

const TEXT_FORMATS: FormatChoice[] = [
  NONE,
  { spec: 'upper', label: 'UPPER CASE' },
  { spec: 'lower', label: 'lower case' },
  { spec: 'title', label: 'Title Case' },
  { spec: 'slug', label: 'slug_style' },
  { spec: 'trunc(10)', label: 'First 10 characters' },
]

const DATE_FORMATS: FormatChoice[] = [
  NONE,
  { spec: 'YYYY', label: 'Year (2019)' },
  { spec: 'YYYY-MM', label: 'Year and month (2019-06)' },
  { spec: 'YYYY-MM-DD', label: 'Date (2019-06-14)' },
  { spec: 'YYYYMMDD', label: 'Compact date (20190614)' },
]

const DATETIME_FORMATS: FormatChoice[] = [
  ...DATE_FORMATS,
  { spec: 'YYYY-MM-DD_HHmm', label: 'Date and time (2019-06-14_0830)' },
]

const INTEGER_FORMATS: FormatChoice[] = [
  NONE,
  { spec: '02', label: 'Pad to 2 digits (07)' },
  { spec: '03', label: 'Pad to 3 digits (007)' },
  { spec: '04', label: 'Pad to 4 digits (0007)' },
]

const FLOAT_FORMATS: FormatChoice[] = [
  NONE,
  { spec: '.1f', label: '1 decimal place' },
  { spec: '.2f', label: '2 decimal places' },
  { spec: '.3f', label: '3 decimal places' },
]

/** The formats worth offering for a field of this type (built-ins take text formats). */
export function formatsFor(dtype: string | undefined): FormatChoice[] {
  switch (dtype) {
    case 'date':
      return DATE_FORMATS
    case 'datetime':
      return DATETIME_FORMATS
    case 'integer':
      return INTEGER_FORMATS
    case 'float':
      return FLOAT_FORMATS
    case 'string':
    case 'enum':
    case 'url':
    case undefined:
      return TEXT_FORMATS
    default:
      return [NONE]
  }
}

/** A plausible value of this type, for previewing a template. */
export function sampleValue(dtype: string, label: string): unknown {
  switch (dtype) {
    case 'integer':
      return 7
    case 'float':
      return 3.14159
    case 'boolean':
      return true
    case 'date':
      return '2019-06-14'
    case 'datetime':
      return '2019-06-14T08:30:00+00:00'
    case 'string':
    case 'enum':
    case 'url':
      return label || 'Example'
    default:
      return null
  }
}

/** Types whose values can't be written into a name. */
export const NON_NAMEABLE = new Set([
  'geo',
  'file',
  'file_list',
  'reference',
  'reference_list',
  'tags',
])
