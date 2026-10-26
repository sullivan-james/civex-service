import { useState, type ReactNode } from 'react'
import type { TableSpec } from '../../api/fileAccess'
import type { Schema } from '../../api/schemas'
import type { FilesLayout } from '../../api/views'
import { describeTable, type Draft } from '../../utils/exportBuilder'
import {
  filterKind,
  levelsFor,
  otherTables,
  pluralize,
  selectedFiles,
  tableAll,
  tableDetails,
  tableList,
  findTable,
  trailTo,
  updateTable,
  withFileFields,
  withTable,
  writtenInFolders,
  type TablePattern,
} from '../../utils/exportLevels'
import { TableSettings } from './TableSettings'
import { LAYOUTS, LAYOUT_NAME } from '../../utils/exportLayouts'
import { filterableFields } from '../../utils/hierarchy'
import { displayLabel } from '../../utils/naming'
import { FilterControls } from '../explorer/FilterControls'
import { Button, CheckRow, InfoTip } from '../ui'
import { FolderTree, Plus } from '../ui/icons'
import { LayoutPreview } from './LayoutPreview'

/** A labelled row of an export form. */
export function Row({
  label,
  children,
}: {
  label: string
  children: ReactNode
}) {
  return (
    <div className="space-y-2">
      <div className="text-sm font-semibold text-fg">{label}</div>
      {children}
    </div>
  )
}

/** What goes in the folder, level by level: the kinds of record as they nest
 * (Encounter, then Recording, then Selection), and at each the files to take and
 * the tables to write, as full-row choices. The first step of an export, whether
 * it is being saved with a schema or run once. */
export function FilesStep({
  schemas,
  scopeSchema,
  draft,
  set,
  withFilter = true,
  fixedKind,
}: {
  schemas: Schema[]
  /** The schema whose tree the levels come from; none means every kind. */
  scopeSchema?: string
  /** The kind the rows already are, where the export starts from a list of one
   * kind: the levels are then that kind and what is inside it. */
  fixedKind?: string
  draft: Draft
  set: (patch: Partial<Draft>) => void
  /** A filter needs a kind of record to test, so only where it can be applied. */
  withFilter?: boolean
}) {
  const label = (name: string) =>
    displayLabel(name, schemas.find((s) => s.name === name)?.label)
  const levels = levelsFor(schemas, scopeSchema ?? fixedKind)
  const selected = selectedFiles(draft, levels)
  const kindForFilter = filterKind(draft, levels)
  const [filtering, setFiltering] = useState(false)
  const others = otherTables(draft.tables, levels)
  const nothing = !draft.files && draft.tables.length === 0

  const setTable = (p: TablePattern, on: boolean) => {
    const tables = withTable(draft.tables, p, on, 'csv')
    set({ tables, ...(writtenInFolders(tables) ? { layout: 'tree' } : {}) })
  }
  const changeTable = (p: TablePattern, patch: Partial<TableSpec>) =>
    set({ tables: updateTable(draft.tables, p, patch) })
  const setFileField = (kind: string, field: string, on: boolean) => {
    const now = selected[kind] ?? []
    set(
      withFileFields(
        draft,
        levels,
        kind,
        on ? [...now, field] : now.filter((f) => f !== field),
      ),
    )
  }

  return (
    <>
      <Row label="What to include">
        <div className="space-y-2.5">
          {levels.map((l) => {
            const kind = l.schema.name
            const name = label(kind)
            const many = pluralize(name)
            const trail = trailTo(l, levels).map((s) => label(s.name))
            return (
              <section
                key={kind}
                aria-label={name}
                className="space-y-2 rounded-lg border border-border bg-canvas-subtle p-3"
              >
                <header className="flex flex-wrap items-baseline gap-x-2">
                  <h3 className="flex items-center gap-1.5 text-sm font-semibold text-fg">
                    <FolderTree size={14} aria-hidden />
                    {name}
                  </h3>
                  <p className="text-xs text-fg-muted">
                    {trail.length > 1
                      ? `inside ${trail.slice(0, -1).join(' › ')}`
                      : 'top of the export'}
                  </p>
                </header>

                {l.fileFields.length > 0 && (
                  <div
                    role="group"
                    aria-label={`${name} files`}
                    className="flex flex-wrap items-center gap-2"
                  >
                    <span className="mr-1 text-xs font-medium text-fg-muted">
                      Files to include
                    </span>
                    {l.fileFields.map((f) => (
                      <CheckRow
                        key={f}
                        compact
                        className="w-auto"
                        title={displayLabel(f)}
                        checked={(selected[kind] ?? []).includes(f)}
                        onChange={(on) => setFileField(kind, f, on)}
                      />
                    ))}
                  </div>
                )}

                {withFilter && kindForFilter === kind && (
                  <div>
                    {draft.filter || filtering ? (
                      <div className="space-y-1">
                        <p className="text-xs font-medium text-fg-muted">
                          Only {many} where
                        </p>
                        <FilterControls
                          wire={draft.filter}
                          fields={filterableFields(l.schema, schemas)}
                          listedSchema={kind}
                          onChange={(filter) => set({ filter })}
                        />
                      </div>
                    ) : (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setFiltering(true)}
                      >
                        <Plus size={14} aria-hidden /> Only some {many}…
                      </Button>
                    )}
                  </div>
                )}

                <div
                  role="group"
                  aria-label={`${name} tables`}
                  className="space-y-1.5"
                >
                  <TableOption
                    pattern={tableAll(kind)}
                    draft={draft}
                    schemas={schemas}
                    title={`One spreadsheet of all ${many}`}
                    placeholder={many}
                    onToggle={setTable}
                    onChange={changeTable}
                  />
                  <TableOption
                    pattern={tableDetails(kind)}
                    draft={draft}
                    schemas={schemas}
                    title={`Each ${name}’s details, as a sheet in its folder`}
                    placeholder="Details"
                    onToggle={setTable}
                    onChange={changeTable}
                  />
                  {l.children.map((c) => (
                    <TableOption
                      key={c.name}
                      pattern={tableList(kind, c.name)}
                      draft={draft}
                      schemas={schemas}
                      title={`A list of each ${name}’s ${pluralize(label(c.name))}, in its folder`}
                      placeholder={pluralize(label(c.name))}
                      onToggle={setTable}
                      onChange={changeTable}
                    />
                  ))}
                </div>
              </section>
            )
          })}
        </div>
        {nothing && (
          <p role="alert" className="mt-2 text-sm text-danger">
            Choose at least one thing to include.
          </p>
        )}
      </Row>

      {others.length > 0 && (
        <Row label="Other tables">
          <div className="space-y-1.5">
            {others.map((t, i) => (
              <CheckRow
                key={i}
                compact
                title={describeTable(t, schemas)}
                checked
                onChange={() =>
                  set({ tables: draft.tables.filter((x) => x !== t) })
                }
              >
                <TableSettings
                  table={t}
                  title={describeTable(t, schemas)}
                  placeholder="Records"
                  schemas={schemas}
                  onChange={(patch) =>
                    set({
                      tables: draft.tables.map((x) =>
                        x === t ? { ...x, ...patch } : x,
                      ),
                    })
                  }
                />
              </CheckRow>
            ))}
          </div>
        </Row>
      )}
    </>
  )
}

/** One kind of table the step can switch on, as a slim row. While it is on, its
 * format sits on the same row, with the rest (name, columns) behind Customise. */
function TableOption({
  pattern,
  draft,
  schemas,
  title,
  placeholder,
  onToggle,
  onChange,
}: {
  pattern: TablePattern
  draft: Draft
  schemas: Schema[]
  title: string
  /** What the file is called when no name is given, without its extension. */
  placeholder: string
  onToggle: (pattern: TablePattern, on: boolean) => void
  onChange: (pattern: TablePattern, patch: Partial<TableSpec>) => void
}) {
  const table = findTable(draft.tables, pattern)
  return (
    <CheckRow
      compact
      title={title}
      checked={!!table}
      onChange={(on) => onToggle(pattern, on)}
    >
      {table && (
        <TableSettings
          table={table}
          title={title}
          placeholder={placeholder}
          schemas={schemas}
          onChange={(patch) => onChange(pattern, patch)}
        />
      )}
    </CheckRow>
  )
}

/** How the folder is laid out: three pictures to choose between. */
export function LayoutStep({
  draft,
  set,
}: {
  draft: Draft
  set: (patch: Partial<Draft>) => void
}) {
  // A table written in each folder needs a folder per record.
  const needsTree = draft.tables.some((t) => t.where)
  return (
    <div className="space-y-3">
      {needsTree && (
        <p className="flex items-center gap-1 text-sm text-fg-muted">
          Folder per record
          <InfoTip>
            A table written in each record’s folder needs a folder per record.
          </InfoTip>
        </p>
      )}
      <div
        role="radiogroup"
        aria-label="Layout"
        className="grid gap-4 md:grid-cols-3"
      >
        {LAYOUTS.map((l: FilesLayout) => (
          <label
            key={l}
            className={`flex flex-col gap-3 rounded-lg border p-4 transition-colors ${
              needsTree && l !== 'tree'
                ? 'cursor-not-allowed opacity-50'
                : 'cursor-pointer'
            } ${
              draft.layout === l
                ? 'border-accent bg-accent-subtle ring-1 ring-accent'
                : 'border-border hover:bg-canvas-subtle'
            }`}
          >
            <span className="flex items-center gap-2.5 text-base font-medium text-fg">
              <input
                type="radio"
                name="layout"
                checked={draft.layout === l}
                disabled={needsTree && l !== 'tree'}
                onChange={() => set({ layout: l })}
              />
              {LAYOUT_NAME[l]}
            </span>
            <LayoutPreview layout={l} />
          </label>
        ))}
      </div>
    </div>
  )
}
