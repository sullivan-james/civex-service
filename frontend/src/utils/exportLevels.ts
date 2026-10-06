import type { TableFormat, TableSpec } from '../api/fileAccess'
import type { Schema } from '../api/schemas'
import type { Draft } from './exportBuilder'
import { schemaLevels } from './hierarchy'

/** The export as a person sees it: the folders it makes, one level for each kind
 * of record (Encounter, then Recording inside it, then Selection), with what goes
 * at each level ticked. This module is the one rule for reading those ticks out of
 * a draft and writing them back, so the step shows plain choices while the saved
 * export keeps its own shape (a kind that holds the files, file fields, tables). */
export interface Level {
  schema: Schema
  /** 0 for the top of the tree. */
  depth: number
  /** The kinds directly inside it. */
  children: Schema[]
  /** The file fields this kind defines itself (an inherited one is the level
   * above's). */
  fileFields: string[]
}

const isFile = (f: { type: string }) =>
  f.type === 'file' || f.type === 'file_list'

/** The levels from `scope` down (the schema the export is saved with, or the kind
 * a list is of); every tree when none is given. */
export function levelsFor(schemas: Schema[], scope?: string): Level[] {
  const live = schemas.filter((s) => !s.deleted_at)
  const root = scope ? live.find((s) => s.name === scope) : undefined
  const make = (schema: Schema, depth: number): Level => ({
    schema,
    depth,
    children: live
      .filter((s) => s.parent_id === schema.id)
      .sort((a, b) => a.name.localeCompare(b.name)),
    fileFields: schema.fields.filter(isFile).map((f) => f.name),
  })
  if (root)
    return [
      make(root, 0),
      ...schemaLevels(live, root).map((l) => make(l.schema, l.depth + 1)),
    ]
  return schemaLevels(live).map((l) => make(l.schema, l.depth))
}

// -- tables ------------------------------------------------------------------

/** What a tick stands for: which records are the rows, where it is written and
 * whether it is a row each or one record's fields. */
export interface TablePattern {
  kind: string
  where: string | null
  shape: 'rows' | 'fields'
}

/** One file at the top listing every record of a kind. */
export const tableAll = (kind: string): TablePattern => ({
  kind,
  where: null,
  shape: 'rows',
})
/** A record's own fields, as field and value, in its folder. */
export const tableDetails = (kind: string): TablePattern => ({
  kind,
  where: kind,
  shape: 'fields',
})
/** In each folder of a kind, a table of the records of a kind inside it. */
export const tableList = (parent: string, child: string): TablePattern => ({
  kind: child,
  where: parent,
  shape: 'rows',
})

export const matches = (t: TableSpec, p: TablePattern): boolean =>
  t.kind === p.kind &&
  (t.where ?? null) === p.where &&
  (t.shape ?? 'rows') === p.shape

export const hasTable = (tables: TableSpec[], p: TablePattern): boolean =>
  tables.some((t) => matches(t, p))

/** The tables with this one added (when it isn't there) or taken out. */
export function withTable(
  tables: TableSpec[],
  p: TablePattern,
  on: boolean,
  format: TableFormat,
): TableSpec[] {
  if (!on) return tables.filter((t) => !matches(t, p))
  if (hasTable(tables, p)) return tables
  return [
    ...tables,
    {
      format,
      columns: null,
      kind: p.kind,
      ...(p.where ? { where: p.where } : {}),
      ...(p.shape === 'fields' ? { shape: 'fields' as const } : {}),
    },
  ]
}

/** The table a tick stands for, if it is on. */
export const findTable = (
  tables: TableSpec[],
  p: TablePattern,
): TableSpec | undefined => tables.find((t) => matches(t, p))

/** The tables with the one a tick stands for changed (its format, its name). */
export const updateTable = (
  tables: TableSpec[],
  p: TablePattern,
  patch: Partial<TableSpec>,
): TableSpec[] => tables.map((t) => (matches(t, p) ? { ...t, ...patch } : t))

/** The levels from the top of the tree down to this one, for saying where a
 * folder is ("Encounter › Recording"). Only levels in the export count. */
export function trailTo(level: Level, levels: Level[]): Schema[] {
  const byId = new Map(levels.map((l) => [l.schema.id, l.schema]))
  const trail: Schema[] = []
  let at: Schema | undefined = level.schema
  while (at) {
    trail.unshift(at)
    at = at.parent_id ? byId.get(at.parent_id) : undefined
  }
  return trail
}

/** The patterns the ticks of these levels stand for. */
export function tickPatterns(levels: Level[]): TablePattern[] {
  return levels.flatMap((l) => [
    tableAll(l.schema.name),
    tableDetails(l.schema.name),
    ...l.children.map((c) => tableList(l.schema.name, c.name)),
  ])
}

/** Tables no tick stands for (a custom name's kind, a table of every kind taken,
 * a table of a kind outside these levels): they are looked after under More
 * options, so every table is somewhere a person can see it. */
export function otherTables(tables: TableSpec[], levels: Level[]): TableSpec[] {
  const known = tickPatterns(levels)
  return tables.filter((t) => !known.some((p) => matches(t, p)))
}

/** Whether any table is written in a folder (so the layout must have one). */
export const writtenInFolders = (tables: TableSpec[]): boolean =>
  tables.some((t) => !!t.where)

// -- files -------------------------------------------------------------------

/** Which file fields are on, level by level. The saved export names a kind that
 * holds the files (or any beneath) and a list of fields (none = every one); this
 * is that, spread over the levels. */
export function selectedFiles(
  draft: Draft,
  levels: Level[],
): Record<string, string[]> {
  const out: Record<string, string[]> = {}
  for (const l of levels) {
    const kind = l.schema.name
    out[kind] =
      !draft.files || (draft.holder && draft.holder !== kind)
        ? []
        : l.fileFields.filter(
            (f) => draft.fields.length === 0 || draft.fields.includes(f),
          )
  }
  return out
}

export const filesOn = (draft: Draft, levels: Level[]): boolean =>
  Object.values(selectedFiles(draft, levels)).some((f) => f.length > 0)

/** The draft's file choices after `kind`'s chosen fields become `fields`: the
 * kind that holds the files is the one level that has any (none when several do),
 * and no files at all means tables alone. */
export function withFileFields(
  draft: Draft,
  levels: Level[],
  kind: string,
  fields: string[],
): Partial<Draft> {
  const chosen = { ...selectedFiles(draft, levels), [kind]: fields }
  const kinds = Object.keys(chosen).filter((k) => chosen[k].length > 0)
  const names = kinds.flatMap((k) => chosen[k])
  const every = levels.flatMap((l) => l.fileFields)
  const holder = kinds.length === 1 ? kinds[0] : ''
  return {
    files: names.length > 0,
    holder,
    // Every file field of every level is just "all"; otherwise name them.
    fields:
      holder === '' && names.length === every.length && names.length > 0
        ? []
        : names,
    // A filter tests one kind of record, so it only applies to one.
    ...(holder !== draft.holder ? { filter: null } : {}),
  }
}

/** The kind of record an "only where" filter would test: the one level that holds
 * the files, if exactly one does. */
export function filterKind(draft: Draft, levels: Level[]): string | null {
  const on = Object.entries(selectedFiles(draft, levels)).filter(
    ([, f]) => f.length > 0,
  )
  return on.length === 1 ? on[0][0] : null
}

/** "Selection" -> "Selections": what a heading says when it means several. */
export function pluralize(word: string): string {
  const lower = word.toLowerCase()
  if (
    lower.length > 1 &&
    lower.endsWith('y') &&
    !'aeiou'.includes(lower[lower.length - 2])
  )
    return `${word.slice(0, -1)}ies`
  if (/(s|x|z|ch|sh)$/.test(lower)) return `${word}es`
  return `${word}s`
}
