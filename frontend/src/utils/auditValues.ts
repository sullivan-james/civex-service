import { displayLabel } from './naming'

// Attributes of schemas, collections and views whose stored name reads badly
// once humanised.
const ATTRIBUTE_LABELS: Record<string, string> = {
  display_template: 'Record name',
  default_value: 'Default value',
  filter_tree: 'Filter',
  parent_id: 'Parent schema',
  timezone: 'Time zone',
  schemas: 'Schemas',
}

/** What to call the thing a change is about: the field's label when it still
 * exists, else a readable form of its name. */
export function changeLabel(change: {
  field: string
  label: string | null
}): string {
  return displayLabel(
    change.field,
    change.label ?? ATTRIBUTE_LABELS[change.field],
  )
}

export function isFileRef(value: unknown): value is { filename: string } {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as { filename?: unknown }).filename === 'string'
  )
}

export function isBlank(value: unknown): boolean {
  return (
    value === null ||
    value === undefined ||
    value === '' ||
    (Array.isArray(value) && value.length === 0)
  )
}

/** A value as plain text, cut to one short line: a file by its name, a list
 * joined, anything structured as compact JSON. */
export function valueText(value: unknown): string {
  if (isBlank(value)) return '(none)'
  if (isFileRef(value)) return value.filename
  if (Array.isArray(value)) return value.map(valueText).join(', ')
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
