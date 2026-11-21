import type { Field } from '../api/schemas'

/** What a formula can give (the `result` rule), in plain words, in the order
 * offered. Mirrors `domain/formulas.RESULT_TYPES`; the server checks. */
export const FORMULA_RESULTS: { value: string; label: string }[] = [
  { value: 'float', label: 'A decimal number' },
  { value: 'integer', label: 'A whole number' },
  { value: 'string', label: 'Text' },
  { value: 'boolean', label: 'Yes / no' },
  { value: 'date', label: 'A date' },
  { value: 'datetime', label: 'A date and time' },
]

/** Types a formula can read (`domain/formulas.KIND_OF_DTYPE`, plus another
 * formula). A link is read through its fields (`link.field`). */
const READABLE = new Set([
  'integer',
  'float',
  'string',
  'longtext',
  'enum',
  'url',
  'boolean',
  'date',
  'datetime',
  'tags',
  'formula',
])

export function readableInFormula(dtype: string): boolean {
  return READABLE.has(dtype)
}

/** A formula field as its value is shown: a field of the type it gives, with
 * its unit, so every display of a value (record page, tables) needs no
 * branch of its own. Any other field is returned as it is. */
export function shownAs(field: Field): Field {
  if (field.type !== 'formula') return field
  const rules = field.restrictions ?? {}
  return {
    ...field,
    type: typeof rules.result === 'string' ? rules.result : 'string',
    restrictions: typeof rules.unit === 'string' ? { unit: rules.unit } : {},
  }
}

/** The functions a formula can call, for the editor's insert list
 * (`domain/formulas.FUNCTIONS`; the server is the authority). */
export const FORMULA_FUNCTIONS: {
  name: string
  insert: string
  help: string
}[] = [
  { name: 'round', insert: 'round(, 2)', help: 'Round to places' },
  { name: 'abs', insert: 'abs()', help: 'Without its sign' },
  { name: 'min', insert: 'min(, )', help: 'The smallest' },
  { name: 'max', insert: 'max(, )', help: 'The largest' },
  { name: 'sqrt', insert: 'sqrt()', help: 'Square root' },
  { name: 'log', insert: 'log()', help: 'Natural log (or log(x, base))' },
  { name: 'exp', insert: 'exp()', help: 'e to the power' },
  { name: 'floor', insert: 'floor()', help: 'Round down' },
  { name: 'ceil', insert: 'ceil()', help: 'Round up' },
  {
    name: 'coalesce',
    insert: 'coalesce(, )',
    help: 'The first that isn’t blank',
  },
  { name: 'concat', insert: 'concat(, )', help: 'Join as text' },
  { name: 'str', insert: 'str()', help: 'As text' },
  { name: 'upper', insert: 'upper()', help: 'In capitals' },
  { name: 'lower', insert: 'lower()', help: 'In small letters' },
  { name: 'len', insert: 'len()', help: 'Length of text or tags' },
  {
    name: 'days_between',
    insert: 'days_between(, )',
    help: 'Days from a start to an end',
  },
  {
    name: 'hours_between',
    insert: 'hours_between(, )',
    help: 'Hours from a start to an end',
  },
  { name: 'year', insert: 'year()', help: 'A date’s year' },
  { name: 'month', insert: 'month()', help: 'A date’s month' },
  { name: 'day', insert: 'day()', help: 'A date’s day' },
  { name: 'date_add', insert: 'date_add(, )', help: 'A date some days on' },
]
