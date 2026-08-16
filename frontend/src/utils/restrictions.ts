import type { Field } from '../api/schemas'
import { utcToDatetimeLocal, datetimeLocalToUTC } from './dates'

/**
 * Single source of truth for field restriction handling on the frontend.
 * Keys per type must stay in sync with `_check_restrictions()` in
 * `record_service.py` (see CLAUDE.md § "Field restrictions"). `enum` is not
 * in that table but shares `string`'s `choices` key on the backend (without
 * `max_length`), so it's handled alongside `string` below.
 */

export type FieldType = string

export type Restrictions = Record<string, unknown>

/** Flat form-state shape covering every restriction input across all field types. */
export interface RestrictionState {
  min: string
  max: string
  choices: string
  maxLength: string
  accept: string
  maxSize: string
  minDate: string
  maxDate: string
  refSchema: string
}

export const EMPTY_RESTRICTION_STATE: RestrictionState = {
  min: '',
  max: '',
  choices: '',
  maxLength: '',
  accept: '',
  maxSize: '',
  minDate: '',
  maxDate: '',
  refSchema: '',
}

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
}

/** Format a byte count as a human-readable size (B / KB / MB). */
export function formatBytes(bytes: number): string {
  if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${bytes} B`
}

/** Build a restrictions dict from form state, or undefined if none apply. */
export function build(
  type: FieldType,
  state: RestrictionState,
): Restrictions | undefined {
  const r: Restrictions = {}
  if ((type === 'reference' || type === 'reference_list') && state.refSchema)
    r.schema = state.refSchema
  if (type === 'integer' || type === 'float') {
    if (state.min !== '')
      r.min = type === 'integer' ? parseInt(state.min) : parseFloat(state.min)
    if (state.max !== '')
      r.max = type === 'integer' ? parseInt(state.max) : parseFloat(state.max)
  }
  if (type === 'string' || type === 'enum') {
    if (state.choices.trim())
      r.choices = state.choices
        .split(',')
        .map((c) => c.trim())
        .filter(Boolean)
    if (type === 'string' && state.maxLength !== '')
      r.max_length = parseInt(state.maxLength)
  }
  if (type === 'file' || type === 'file_list') {
    if (state.accept.trim()) r.accept = state.accept.trim()
    if (state.maxSize !== '') r.max_size = parseInt(state.maxSize)
  }
  if (type === 'date') {
    if (state.minDate) r.min = state.minDate
    if (state.maxDate) r.max = state.maxDate
  }
  if (type === 'datetime') {
    if (state.minDate) r.min = datetimeLocalToUTC(state.minDate)
    if (state.maxDate) r.max = datetimeLocalToUTC(state.maxDate)
  }
  return Object.keys(r).length ? r : undefined
}

/** Parse a field's restrictions into form state, for editing. */
export function parse(field: Field): RestrictionState {
  const restrictions = field.restrictions ?? {}
  return {
    min: restrictions.min !== undefined ? String(restrictions.min) : '',
    max: restrictions.max !== undefined ? String(restrictions.max) : '',
    choices: Array.isArray(restrictions.choices)
      ? (restrictions.choices as string[]).join(', ')
      : '',
    maxLength:
      restrictions.max_length !== undefined
        ? String(restrictions.max_length)
        : '',
    accept: typeof restrictions.accept === 'string' ? restrictions.accept : '',
    maxSize:
      restrictions.max_size !== undefined ? String(restrictions.max_size) : '',
    minDate:
      restrictions.min !== undefined
        ? field.type === 'datetime'
          ? utcToDatetimeLocal(String(restrictions.min))
          : String(restrictions.min)
        : '',
    maxDate:
      restrictions.max !== undefined
        ? field.type === 'datetime'
          ? utcToDatetimeLocal(String(restrictions.max))
          : String(restrictions.max)
        : '',
    refSchema:
      typeof restrictions.schema === 'string' ? restrictions.schema : '',
  }
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
  return parts.join(' · ')
}

/** Derive input props (choices, min/max, accept, etc.) for DynamicField. */
export function toInputProps(field: Field): InputProps {
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
  if (field.type === 'date') {
    if (restrictions.min !== undefined) props.minDate = String(restrictions.min)
    if (restrictions.max !== undefined) props.maxDate = String(restrictions.max)
  }
  if (field.type === 'datetime') {
    if (restrictions.min !== undefined)
      props.minDate = utcToDatetimeLocal(String(restrictions.min))
    if (restrictions.max !== undefined)
      props.maxDate = utcToDatetimeLocal(String(restrictions.max))
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
