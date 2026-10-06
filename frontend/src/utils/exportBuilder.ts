import type {
  CreateExportDefinition,
  ExportDefinition,
} from '../api/exportDefinitions'
import type { FileSelection, TableSpec } from '../api/fileAccess'
import type { Schema } from '../api/schemas'
import type { FilesLayout } from '../api/views'
import { LAYOUT_SHORT } from './exportLayouts'
import { TABLE_FORMAT_NAME } from './tableFormats'
import type { FilterTreeWire } from './filterTree'
import { schemaLevels, schemasById } from './hierarchy'
import { displayLabel } from './naming'
import { collectFields, joinableColumns } from './viewFields'

/** What is being decided while building an export for a schema. It has no
 * collection and no record: those are where the export is *run*, not part of
 * what it is. */
export interface Draft {
  name: string
  /** The kind of record that holds the files ('' = any kind beneath). */
  holder: string
  /** Only these file fields ([] = every file field). */
  fields: string[]
  /** Which of those records (only meaningful with a `holder`). */
  filter: FilterTreeWire | null
  layout: FilesLayout
  /** Whether the files themselves are exported (false: tables alone). */
  files: boolean
  /** The tables made beside the files (or instead of them), each its own. */
  tables: TableSpec[]
}

export const emptyDraft: Draft = {
  name: '',
  holder: '',
  fields: [],
  filter: null,
  layout: 'tree',
  files: true,
  tables: [],
}

/** The schema and every kind beneath it, live ones only: where files can be.
 * With no schema named, every live kind. */
export function kindsIn(schemas: Schema[], schemaName?: string): Schema[] {
  const live = schemas.filter((s) => !s.deleted_at)
  if (!schemaName) return live
  const root = live.find((s) => s.name === schemaName)
  if (!root) return []
  return [root, ...schemaLevels(live, root).map((l) => l.schema)]
}

/** The columns a table of one kind can have: its fields (own and inherited) and
 * one hop through each reference, in the shape the column picker takes. */
export function tableColumnChoices(schemas: Schema[], kind: string) {
  const byId = schemasById(schemas)
  const byName = new Map(schemas.map((s) => [s.name, s]))
  const schema = byName.get(kind)
  return {
    baseFields: schema ? collectFields(schema, byId) : [],
    joinable: schema ? joinableColumns(schema, byId, byName) : [],
  }
}

/** A table in words: what it lists, where it goes, in what. */
export function describeTable(spec: TableSpec, schemas?: Schema[]): string {
  const label = (n: string) =>
    displayLabel(n, schemas?.find((s) => s.name === n)?.label)
  const what = spec.kind ? label(spec.kind) : 'each kind taken'
  const where = !spec.where
    ? 'at the top'
    : spec.where === spec.kind && spec.shape === 'fields'
      ? 'in each record’s folder, as its details'
      : `in each ${label(spec.where)} folder`
  return `${TABLE_FORMAT_NAME[spec.format]} of ${what} ${where}${
    spec.columns ? ` · ${spec.columns.length} columns` : ''
  }`
}

/** What to save. */
export function definitionBody(draft: Draft): CreateExportDefinition {
  return {
    name: draft.name.trim(),
    holder: draft.holder || null,
    fields: draft.files ? draft.fields : [],
    // A filter tests one kind of record, so it only applies when there is one.
    filter_tree: draft.holder ? draft.filter : null,
    files_layout: draft.layout,
    include_files: draft.files,
    tables: draft.tables,
  }
}

/** The draft an existing export stands for, to change it. */
export function draftFrom(def: ExportDefinition): Draft {
  return {
    name: def.name,
    holder: def.holder ?? '',
    fields: def.fields,
    filter: def.filter_tree,
    layout: def.files_layout,
    files: def.include_files,
    tables: def.tables,
  }
}

/** The selection a draft would take across all the data, to preview the folder
 * before saving it. */
export function previewSelection(
  draft: Draft,
  schemaName: string,
  schemas: Schema[],
): FileSelection {
  return {
    schema_name: draft.holder || undefined,
    kinds: draft.holder
      ? undefined
      : kindsIn(schemas, schemaName).map((s) => s.name),
    filter: draft.holder && draft.filter ? draft.filter : undefined,
    fields: draft.files && draft.fields.length > 0 ? draft.fields : undefined,
    layout: draft.layout,
    files: draft.files ? undefined : false,
    tables: draft.tables,
  }
}

/** One line saying what an export takes and how it is laid out. */
export function describeDefinition(
  def: Pick<
    ExportDefinition,
    'holder' | 'fields' | 'files_layout' | 'filter_tree'
  > &
    Partial<Pick<ExportDefinition, 'include_files' | 'tables'>>,
  schemas?: Schema[],
): string {
  const label = (name: string) =>
    displayLabel(name, schemas?.find((s) => s.name === name)?.label)
  const kind = def.holder ? label(def.holder) : 'any kind beneath'
  const withFiles = def.include_files !== false
  const files = def.fields.length > 0 ? def.fields.join(', ') : 'every file'
  return [
    withFiles ? `${files} of ${kind}` : `Tables of ${kind}`,
    (def.tables ?? []).length > 0
      ? (def.tables ?? []).length === 1
        ? describeTable(def.tables![0], schemas)
        : `${def.tables!.length} tables`
      : null,
    def.filter_tree ? 'filtered' : null,
    withFiles ? LAYOUT_SHORT[def.files_layout] : null,
  ]
    .filter(Boolean)
    .join(' · ')
}

/** A draft that starts from a saved export, to run it with changes. */
export function draftFromSaved(def: ExportDefinition): Draft {
  return draftFrom(def)
}

/** Where a one-off export is being asked for, and so what it is limited to: the
 * records it was started from. */
export type ExportContext = FileSelection

/** The selection for a one-off export: the context it was started in (a record,
 * a collection, a list) narrowed by what was chosen. A kind narrows by schema
 * where the context names none, and otherwise (a list of Encounters taking what
 * is inside them) by kinds, since the list's own kind stays. */
export function oneTimeSelection(
  context: ExportContext,
  draft: Draft,
  scopeKinds?: string[],
): FileSelection {
  const selection: FileSelection = {
    ...context,
    layout: draft.layout,
    fields: draft.files && draft.fields.length > 0 ? draft.fields : undefined,
    files: draft.files ? undefined : false,
    tables: draft.tables,
  }
  if (draft.holder) {
    if (context.schema_name || context.record_ids)
      selection.kinds = [draft.holder]
    else {
      selection.schema_name = draft.holder
      if (draft.filter) selection.filter = draft.filter
    }
  } else if (scopeKinds && !context.schema_name && !context.record_ids) {
    selection.kinds = scopeKinds
  }
  return selection
}
