import type {
  ColumnChoice,
  ImportBatch,
  ImportColumn,
  ImportRequest,
  ImportSheet,
} from '../../api/imports'
import type { Schema } from '../../api/schemas'
import { slugify } from '../../utils/naming'

/** What a column can be brought in as, in the words a person uses. The keys are
 * the field types a spreadsheet cell can fill. */
export const IMPORT_TYPES: { value: string; label: string }[] = [
  { value: 'string', label: 'Text' },
  { value: 'longtext', label: 'Long text' },
  { value: 'integer', label: 'Whole number' },
  { value: 'float', label: 'Number' },
  { value: 'boolean', label: 'Yes or no' },
  { value: 'date', label: 'Date' },
  { value: 'datetime', label: 'Date and time' },
  { value: 'url', label: 'Link' },
]

/** Field types a row can be matched by (a key is made of these). */
const MATCHABLE = new Set([
  'string',
  'longtext',
  'integer',
  'float',
  'boolean',
  'date',
  'datetime',
  'enum',
  'url',
])

/** What one column is set to: left out, put in a field that is there, or in a
 * field made for it. */
export const NEW_FIELD = '__new__'
export const LEAVE_OUT = '__skip__'

export interface ColumnSetting {
  heading: string
  /** A field's key, `NEW_FIELD` or `LEAVE_OUT`. */
  goesIn: string
  /** The type of a field made. */
  dtype: string
}

/** The kind being brought into: one that is there, or a new one with a name. */
export type Target =
  { kind: 'existing'; name: string } | { kind: 'new'; label: string }

/** A kind's key for a name a person typed, different from every kind there is. */
export function kindKeyFor(label: string, taken: string[]): string {
  const base = slugify(label) || 'records'
  let key = base
  for (let n = 2; taken.includes(key); n++) key = `${base}_${n}`
  return key
}

/** The name a new kind starts with: the file's own name, without its extension. */
export function nameFromFile(filename: string): string {
  const stem = filename
    .replace(/\.[^.]+$/, '')
    .replace(/[_-]+/g, ' ')
    .trim()
  return stem ? stem[0].toUpperCase() + stem.slice(1) : 'Imported records'
}

/** Where each column goes to start with: a field of the kind with the column's
 * key (or its heading as a name) when there is one, else a new field of the type
 * the first rows suggest. */
export function suggestSettings(
  columns: ImportColumn[],
  schema: Schema | undefined,
): ColumnSetting[] {
  const fields = schema?.fields ?? []
  const used = new Set<string>()
  return columns.map((c) => {
    const found = fields.find(
      (f) =>
        !used.has(f.name) &&
        (f.name === c.key ||
          (f.label ?? '').trim().toLowerCase() ===
            c.label.trim().toLowerCase()),
    )
    if (found) {
      used.add(found.name)
      return { heading: c.heading, goesIn: found.name, dtype: c.dtype }
    }
    return { heading: c.heading, goesIn: NEW_FIELD, dtype: c.dtype }
  })
}

/** The column a first import is matched by: the one going in the first unique
 * key's field when the kind has a one-field key, else none. */
export function suggestMatch(
  settings: ColumnSetting[],
  schema: Schema | undefined,
): string {
  const key = schema?.unique_keys?.find((k) => k.length === 1)?.[0]
  const column = settings.find((s) => s.goesIn === key)
  return column?.heading ?? ''
}

/** The keys the new fields get: each column's own, kept apart from the fields
 * already there. */
function newKeys(
  columns: ImportColumn[],
  settings: ColumnSetting[],
  schema: Schema | undefined,
): Map<string, string> {
  const taken = new Set((schema?.fields ?? []).map((f) => f.name))
  const keys = new Map<string, string>()
  columns.forEach((c, i) => {
    if (settings[i]?.goesIn !== NEW_FIELD) return
    let key = c.key
    for (let n = 2; taken.has(key); n++) key = `${c.key}_${n}`
    taken.add(key)
    keys.set(c.heading, key)
  })
  return keys
}

/** The field each column goes in, by heading: existing or made; left out ones
 * are not in it. */
export function fieldsOf(
  columns: ImportColumn[],
  settings: ColumnSetting[],
  schema: Schema | undefined,
): Map<string, string> {
  const made = newKeys(columns, settings, schema)
  const out = new Map<string, string>()
  for (const s of settings) {
    if (s.goesIn === LEAVE_OUT) continue
    out.set(s.heading, s.goesIn === NEW_FIELD ? made.get(s.heading)! : s.goesIn)
  }
  return out
}

/** Columns a record can be matched by: the ones put in a field of a type that
 * compares as one value. */
export function matchable(
  columns: ImportColumn[],
  settings: ColumnSetting[],
  schema: Schema | undefined,
): ImportColumn[] {
  return columns.filter((c, i) => {
    const s = settings[i]
    if (!s || s.goesIn === LEAVE_OUT) return false
    if (s.goesIn === NEW_FIELD) return MATCHABLE.has(s.dtype)
    const field = schema?.fields.find((f) => f.name === s.goesIn)
    return !!field && MATCHABLE.has(field.type)
  })
}

export interface Choices {
  filename: string
  sha256: string
  sheet: ImportSheet
  target: Target
  schema: Schema | undefined
  collection: string
  /** The collection is to be made. */
  newCollection: boolean
  settings: ColumnSetting[]
  /** The heading of the column rows are matched by; '' for none. */
  match: string
  ifExists: ImportRequest['if_exists']
  /** The kinds there are, for a new kind's key. */
  kinds: string[]
}

/** What to ask the server for, from what the person chose. */
export function buildRequest(c: Choices): ImportRequest {
  const fields = fieldsOf(c.sheet.columns, c.settings, c.schema)
  const columns: ColumnChoice[] = c.sheet.columns.map((col, i) => {
    const s = c.settings[i]
    const field = fields.get(col.heading) ?? null
    return {
      heading: col.heading,
      field,
      create: s.goesIn === NEW_FIELD,
      dtype: s.dtype,
      label: col.label,
    }
  })
  const kind =
    c.target.kind === 'existing'
      ? c.target.name
      : kindKeyFor(c.target.label, c.kinds)
  const match = c.match ? fields.get(c.match) : undefined
  return {
    sha256: c.sha256,
    filename: c.filename,
    sheet: c.sheet.sheet,
    collection: c.collection.trim(),
    new_collection: c.newCollection,
    kind,
    kind_label: c.target.kind === 'new' ? c.target.label.trim() : null,
    columns,
    match_on: match ? [match] : [],
    if_exists: match ? c.ifExists : 'add_new',
  }
}

/** Why the choices can't be used yet, in a sentence; null when they can. */
export function whyNot(c: Choices): string | null {
  if (c.newCollection && !c.collection.trim()) return 'Name the new collection.'
  if (c.target.kind === 'new' && !c.target.label.trim())
    return 'Name the new kind of record.'
  const going = c.settings.filter((s) => s.goesIn !== LEAVE_OUT)
  if (going.length === 0) return 'Choose at least one column to bring in.'
  const used = going.filter((s) => s.goesIn !== NEW_FIELD).map((s) => s.goesIn)
  if (new Set(used).size !== used.length)
    return 'Two columns go in the same field.'
  return null
}

/** The rows of a problem list by their number: "Row 5: why" is for row 5. */
export function problemsByRow(problems: string[]): Map<number, string> {
  const out = new Map<number, string>()
  for (const p of problems) {
    const m = /^Row (\d+): (.*)$/s.exec(p)
    if (m && !out.has(Number(m[1]))) out.set(Number(m[1]), m[2])
  }
  return out
}

export interface Totals {
  read: number
  created: number
  updated: number
  unchanged: number
  skipped: number
  problems: string[]
}

export const NO_TOTALS: Totals = {
  read: 0,
  created: 0,
  updated: 0,
  unchanged: 0,
  skipped: 0,
  problems: [],
}

/** Most problems kept to show; the counts stay exact. */
export const MAX_PROBLEMS = 200

export function addTotals(t: Totals, part: ImportBatch): Totals {
  return {
    read: t.read + part.read,
    created: t.created + part.created,
    updated: t.updated + part.updated,
    unchanged: t.unchanged + part.unchanged,
    skipped: t.skipped + part.skipped,
    problems: [...t.problems, ...part.problems].slice(0, MAX_PROBLEMS),
  }
}

/** Rows asked for in one request. */
export const PART_ROWS = 2000

/** Goes through the file a part at a time, telling `onPart` after each one so
 * progress can show, and stopping when `signal` aborts or a request fails: the
 * rows done so far are in the result with the row to carry on from. */
export async function runInParts(
  run: (start: number, limit: number) => Promise<ImportBatch>,
  total: number,
  onPart: (totals: Totals, next: number) => void,
  options: { from?: number; totals?: Totals; signal?: AbortSignal } = {},
): Promise<{
  totals: Totals
  next: number
  error: unknown
  cancelled: boolean
}> {
  let totals = options.totals ?? NO_TOTALS
  let next = options.from ?? 0
  try {
    while (next < total) {
      if (options.signal?.aborted)
        return { totals, next, error: null, cancelled: true }
      const part = await run(next, PART_ROWS)
      totals = addTotals(totals, part)
      next += Math.max(part.read, 0)
      onPart(totals, next)
      if (part.done || part.read === 0) break
    }
  } catch (error) {
    return { totals, next, error, cancelled: false }
  }
  return { totals, next, error: null, cancelled: false }
}

/** "12 records added, 3 changed, 40 already there." */
export function summary(t: Totals): string {
  const parts = [`${t.created.toLocaleString()} added`]
  if (t.updated) parts.push(`${t.updated.toLocaleString()} changed`)
  if (t.unchanged) parts.push(`${t.unchanged.toLocaleString()} already there`)
  return parts.join(', ') + '.'
}
