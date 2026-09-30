import type { Field } from '../api/schemas'
import { knownTimeZone, utcToZonedLocal, zonedLocalToUTC } from './dates'

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
  /** datetime only: IANA zone overriding the collection's; '' = inherit. */
  timezone: string
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
  timezone: '',
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
    // Bounds are typed as wall time in the field's own zone (else the
    // viewer's) and stored as UTC instants. boundsProblem() has already
    // vetted them; an unresolvable one is dropped rather than stored naive,
    // which the server would silently ignore when comparing.
    const zone = state.timezone || null
    if (state.timezone) r.timezone = state.timezone
    const min = state.minDate ? zonedLocalToUTC(state.minDate, zone) : ''
    const max = state.maxDate ? zonedLocalToUTC(state.maxDate, zone) : ''
    if (min) r.min = min
    if (max) r.max = max
  }
  return Object.keys(r).length ? r : undefined
}

/** Why the datetime bounds in `state` can't be saved, or null if they can. */
export function boundsProblem(
  type: FieldType,
  state: RestrictionState,
): string | null {
  if (type !== 'datetime') return null
  const zone = state.timezone || null
  for (const [label, value] of [
    ['Not before', state.minDate],
    ['Not after', state.maxDate],
  ] as const) {
    if (value && zonedLocalToUTC(value, zone) === null) {
      return `${label}: that time doesn't exist or is ambiguous in ${zone ?? 'your timezone'} (a clock change). Pick another time.`
    }
  }
  return null
}

/** Parse a field's restrictions into form state, for editing. */
export function parse(field: Field): RestrictionState {
  const restrictions = field.restrictions ?? {}
  const timezone =
    typeof restrictions.timezone === 'string' ? restrictions.timezone : ''
  // Bounds are shown in the field's own zone (else the viewer's) -- the
  // same zone build() reads them in, so they round-trip.
  const zone = knownTimeZone(timezone)
  return {
    timezone,
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
          ? utcToZonedLocal(String(restrictions.min), zone)
          : String(restrictions.min)
        : '',
    maxDate:
      restrictions.max !== undefined
        ? field.type === 'datetime'
          ? utcToZonedLocal(String(restrictions.max), zone)
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
  if (field.type === 'date') {
    if (restrictions.min !== undefined) props.minDate = String(restrictions.min)
    if (restrictions.max !== undefined) props.maxDate = String(restrictions.max)
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
