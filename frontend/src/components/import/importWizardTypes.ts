import type { CivexRecord } from '../../api/records'
import type { FieldType } from '../../utils/fieldTypes'
import { parseLocation } from '../../utils/geo'
import { convert, parseQuantity, tidy } from '../../utils/units'

export type Mode = 'files' | 'csv'
export type WizardStep = 'source' | 'map' | 'confirm' | 'done'
export type Strategy = 'create' | 'match'

export interface NewFieldDraft {
  name: string
  label: string
  type: string
}

/** Everything the Map step owns. Grouped into one object (rather than one
 * `useState` per field) since this step alone has over a dozen pieces of
 * state — a single `patch` setter keeps adding a new mapping option a
 * one-place change instead of new props threaded through every layer. */
export interface MapState {
  schemaChoice: string
  newSchema: { label: string; name: string }
  parentRecordId: string
  columnMap: Record<string, string>
  /** CSV column -> unit its values are written in, when that differs from
   * the unit of the numeric field it maps to. Absent = the field's unit. */
  columnUnits: Record<string, string>
  newColumnFields: Record<string, NewFieldDraft>
  fileFieldChoice: string
  newFileField: NewFieldDraft
  strategyChoice: Strategy
  keyFieldName: string
  pattern: string
  extraExtractEnabled: boolean
  extraFieldChoice: string
  newExtraField: NewFieldDraft
}

export function initialMapState(): MapState {
  return {
    schemaChoice: '',
    newSchema: { label: '', name: '' },
    parentRecordId: '',
    columnMap: {},
    columnUnits: {},
    newColumnFields: {},
    fileFieldChoice: '',
    newFileField: { name: 'file', label: 'File', type: 'file' },
    strategyChoice: 'create',
    keyFieldName: '',
    pattern: '',
    extraExtractEnabled: false,
    extraFieldChoice: '',
    newExtraField: { name: '', label: '', type: 'string' },
  }
}

/** Everything the Confirm step owns: the automation opt-in, and (only when
 * no collection was pre-supplied) the collection choice. */
export interface ConfirmState {
  saveAsAutomation: boolean
  automationLabel: string
  collectionChoice: string
  newCollection: { name: string; description: string }
}

export function initialConfirmState(): ConfirmState {
  return {
    saveAsAutomation: false,
    automationLabel: '',
    collectionChoice: '',
    newCollection: { name: '', description: '' },
  }
}

/** Types creatable inline mid-import from just {name, label, type} --
 * file/file_list are their own dedicated wizard step (not a generic field
 * choice), reference/reference_list need a target-schema restriction the
 * wizard's draft shape has nowhere to hold, and enum needs `choices` to be
 * usable. All of those stay a schema-page (FieldForm) job, done after the
 * import creates the field with a sane inferred type. A subset of the
 * canonical FIELD_TYPES (`utils/fieldTypes.ts`), typed against it so a type
 * renamed there is a compile error here instead of a silent drift. */
export const RESTRICTION_FREE_TYPES: readonly FieldType[] = [
  'string',
  'integer',
  'float',
  'boolean',
  'date',
  'datetime',
  'url',
  'tags',
  'geo',
  'longtext',
]

export const NEW_SCHEMA = '__new__'
export const NEW_COLLECTION = '__new__'
export const NEW_FIELD = '__new__'
export const SKIP_COLUMN = '__skip__'

export interface CsvRowPlan {
  index: number
  data: Record<string, unknown>
  skip: string | null
}

export interface FilePlan {
  file: File
  data: Record<string, unknown>
  matchedRecord: CivexRecord | null
  skip: string | null
}

export interface ImportOutcome {
  created: CivexRecord[]
  updated: CivexRecord[]
  skipped: { label: string; reason: string }[]
  automationStem?: string
  automationError?: string
}

export function coerceCsvValue(
  raw: string,
  dtype: string,
  /** The numeric field's unit, and the unit this column is written in. */
  units?: { fieldUnit?: string; columnUnit?: string },
): { value: unknown; error: string | null } {
  const trimmed = raw.trim()
  if (trimmed === '') return { value: undefined, error: null }
  if (dtype === 'geo') {
    const g = parseLocation(trimmed)
    return g
      ? { value: g, error: null }
      : {
          value: undefined,
          error: `"${raw}" is not a location (use "latitude, longitude")`,
        }
  }
  if (dtype === 'float' && units?.fieldUnit) {
    // Stored values are always in the field's unit: convert on the way in so
    // a column of feet can never land in a metres field as-is.
    const q = parseQuantity(trimmed)
    if (!q) return { value: undefined, error: `"${raw}" is not a number` }
    const from = q.unit ?? units.columnUnit ?? units.fieldUnit
    const r = convert(q.value, from, units.fieldUnit)
    return 'error' in r
      ? { value: undefined, error: r.error }
      : { value: parseFloat(tidy(r.value)), error: null }
  }
  if (dtype === 'integer') {
    const n = parseInt(trimmed, 10)
    return isNaN(n)
      ? { value: undefined, error: `"${raw}" is not an integer` }
      : { value: n, error: null }
  }
  if (dtype === 'float') {
    const n = parseFloat(trimmed)
    return isNaN(n)
      ? { value: undefined, error: `"${raw}" is not a number` }
      : { value: n, error: null }
  }
  if (dtype === 'boolean') {
    return {
      value: ['true', 'yes', '1'].includes(trimmed.toLowerCase()),
      error: null,
    }
  }
  return { value: trimmed, error: null }
}
