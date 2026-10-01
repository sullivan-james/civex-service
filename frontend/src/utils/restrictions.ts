import type { Field } from '../api/schemas'
import { utcToZonedLocal } from './dates'
import type { Precision } from './partialDates'

/**
 * Single source of truth for field restriction handling on the frontend.
 * What a field's rules *mean* when reading them: summaries and the props
 * `DynamicField` needs. Which rules exist, and how they are edited, comes
 * from the server's field-type descriptors (`hooks/useFieldTypes.ts`,
 * `components/schemas/RestrictionControls.tsx`). Keys must stay in sync with
 * `_check_restrictions()` in `record_service.py`.
 */

export type FieldType = string

export type Restrictions = Record<string, unknown>

export interface InputProps {
  choices?: string[]
  maxLength?: number
  min?: number
  max?: number
  minDate?: string
  maxDate?: string
  accept?: string
  maxSize?: number
  targetSchema?: string
  unit?: string
  precision?: Precision
  geometryTypes?: string[]
}

/** Format a byte count as a human-readable size (B / KB / MB). */
export function formatBytes(bytes: number): string {
  if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${bytes} B`
}

/** Format restrictions as a short display string, e.g. "min 0 · max 100". */
export function summarise(
  restrictions: Restrictions | undefined,
  type: FieldType,
): string {
  if (!restrictions || !Object.keys(restrictions).length) return ''
  const parts: string[] = []
  if (type === 'integer' || type === 'float') {
    if (restrictions.min !== undefined) parts.push(`min ${restrictions.min}`)
    if (restrictions.max !== undefined) parts.push(`max ${restrictions.max}`)
  }
  if (type === 'float' && typeof restrictions.unit === 'string')
    parts.push(`in ${restrictions.unit}`)
  if (type === 'geo') {
    if (Array.isArray(restrictions.geometry_types))
      parts.push((restrictions.geometry_types as string[]).join(', '))
    if (Array.isArray(restrictions.bbox)) parts.push('limited area')
  }
  if (type === 'date' && typeof restrictions.precision === 'string')
    parts.push(`${restrictions.precision} or finer`)
  if (type === 'string' || type === 'enum') {
    if (Array.isArray(restrictions.choices))
      parts.push(`choices: ${(restrictions.choices as string[]).join(', ')}`)
    if (restrictions.max_length !== undefined)
      parts.push(`max ${restrictions.max_length} chars`)
  }
  if (type === 'file' || type === 'file_list') {
    if (restrictions.accept) parts.push(`accept ${restrictions.accept}`)
    if (restrictions.max_size !== undefined)
      parts.push(`max ${formatBytes(Number(restrictions.max_size))}`)
  }
  if (type === 'date' || type === 'datetime') {
    if (restrictions.min !== undefined) parts.push(`from ${restrictions.min}`)
    if (restrictions.max !== undefined) parts.push(`until ${restrictions.max}`)
  }
  if (type === 'datetime' && typeof restrictions.timezone === 'string')
    parts.push(`timezone ${restrictions.timezone}`)
  return parts.join(' · ')
}

/** Derive input props (choices, min/max, accept, etc.) for DynamicField.
 * `timeZone` is the field's effective zone: datetime bounds (UTC instants)
 * are expressed in it so the input's min/max match what the user types. */
export function toInputProps(
  field: Field,
  timeZone: string | null = null,
): InputProps {
  const restrictions = field.restrictions ?? {}
  const props: InputProps = {}
  if (field.type === 'string' || field.type === 'enum') {
    if (Array.isArray(restrictions.choices))
      props.choices = restrictions.choices as string[]
  }
  if (field.type === 'string' && restrictions.max_length !== undefined) {
    props.maxLength = Number(restrictions.max_length)
  }
  if (field.type === 'integer' || field.type === 'float') {
    if (restrictions.min !== undefined) props.min = Number(restrictions.min)
    if (restrictions.max !== undefined) props.max = Number(restrictions.max)
  }
  if (field.type === 'float' && typeof restrictions.unit === 'string')
    props.unit = restrictions.unit
  if (field.type === 'geo' && Array.isArray(restrictions.geometry_types))
    props.geometryTypes = restrictions.geometry_types as string[]
  if (field.type === 'date') {
    if (restrictions.min !== undefined) props.minDate = String(restrictions.min)
    if (restrictions.max !== undefined) props.maxDate = String(restrictions.max)
    props.precision =
      restrictions.precision === 'year' || restrictions.precision === 'month'
        ? restrictions.precision
        : 'day'
  }
  if (field.type === 'datetime') {
    if (restrictions.min !== undefined)
      props.minDate = utcToZonedLocal(String(restrictions.min), timeZone)
    if (restrictions.max !== undefined)
      props.maxDate = utcToZonedLocal(String(restrictions.max), timeZone)
  }
  if (field.type === 'file' || field.type === 'file_list') {
    if (typeof restrictions.accept === 'string')
      props.accept = restrictions.accept
    if (restrictions.max_size !== undefined)
      props.maxSize = Number(restrictions.max_size)
  }
  if (
    (field.type === 'reference' || field.type === 'reference_list') &&
    typeof restrictions.schema === 'string'
  ) {
    props.targetSchema = restrictions.schema
  }
  return props
}
