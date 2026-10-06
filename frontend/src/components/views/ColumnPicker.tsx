import { useState } from 'react'
import { useRangeSelect } from '../../hooks/useRangeSelect'
import { displayLabel } from '../../utils/naming'
import type { JoinableColumn, ResolvedField } from '../../utils/viewFields'
import { Button, Checkbox, Input, SortableList } from '../ui'

/** A column that is not a field: the record's own id and dates. */
export interface ExtraColumn {
  name: string
  label: string
}

interface ColumnPickerProps {
  /** The columns shown, in order. */
  columns: string[]
  onChange: (columns: string[]) => void
  baseFields: ResolvedField[]
  joinable: JoinableColumn[]
  /** Columns beyond the fields (a table of records has the id, created, updated). */
  extra?: ExtraColumn[]
  /** Offer "Hide all" (off where an empty list means the default columns). */
  allowHideAll?: boolean
}

export function columnLabel(
  col: string,
  baseFields: ResolvedField[],
  joinable: JoinableColumn[],
  extra: ExtraColumn[] = [],
): string {
  const known = extra.find((e) => e.name === col)
  if (known) return known.label
  if (!col.includes('.')) {
    const field = baseFields.find((f) => f.name === col)
    return field ? displayLabel(field.name, field.label) : col
  }
  const join = joinable.find((j) => j.value === col)
  return join ? join.label : col
}

interface Group {
  /** null: no heading (everything is of one kind). */
  title: string | null
  items: { value: string; label: string }[]
}

/** Which columns, and in what order: one list. The columns shown are at the top
 * in the order they will have, each with a box to take it out and arrows or a
 * drag handle to move it; the ones not shown are below, grouped by where they come
 * from, with a search, to put in. Boxes in the not-shown list pick a run with shift-click. */
export function ColumnPicker({
  columns,
  onChange,
  baseFields,
  joinable,
  extra = [],
  allowHideAll = true,
}: ColumnPickerProps) {
  const [search, setSearch] = useState('')

  // Everything that could be shown, grouped by where it comes from.
  const groups: Group[] = []
  if (extra.length > 0)
    groups.push({
      title: 'The record',
      items: extra.map((e) => ({ value: e.name, label: e.label })),
    })
  const sources = [...new Set(baseFields.map((f) => f.sourceSchemaName))]
  for (const source of sources)
    groups.push({
      title: sources.length > 1 ? `Fields from ${displayLabel(source)}` : null,
      items: baseFields
        .filter((f) => f.sourceSchemaName === source)
        .map((f) => ({
          value: f.name,
          label: displayLabel(f.name, f.label),
        })),
    })
  const byRef = new Map<string, JoinableColumn[]>()
  for (const j of joinable)
    byRef.set(j.refField.name, [...(byRef.get(j.refField.name) ?? []), j])
  for (const [ref, joins] of byRef)
    groups.push({
      title: `From the linked ${displayLabel(ref, joins[0].refField.label)}`,
      items: joins.map((j) => ({
        value: j.value,
        label: displayLabel(j.targetField.name, j.targetField.label),
      })),
    })

  const wanted = search.trim().toLowerCase()
  const notShown = groups
    .map((g) => ({
      ...g,
      items: g.items.filter(
        (i) =>
          !columns.includes(i.value) &&
          (!wanted || i.label.toLowerCase().includes(wanted)),
      ),
    }))
    .filter((g) => g.items.length > 0)
  const range = useRangeSelect(
    notShown.flatMap((g) => g.items.map((i) => i.value)),
  )

  function add(col: string) {
    // Shift-click: everything from the last box clicked to this one comes in.
    const ids = range.rangeFor(col) ?? [col]
    onChange([...columns, ...ids.filter((c) => !columns.includes(c))])
  }
  const label = (col: string) => columnLabel(col, baseFields, joinable, extra)

  return (
    <div className="space-y-4">
      <section className="space-y-1.5">
        <div className="flex items-center justify-between gap-2">
          <h4 className="text-sm font-semibold text-fg">
            Shown ({columns.length}){' '}
            <span className="font-normal text-fg-muted">in this order</span>
          </h4>
          <span className="flex gap-1">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => onChange(baseFields.map((f) => f.name))}
            >
              Show every field
            </Button>
            {allowHideAll && (
              <Button
                size="sm"
                variant="ghost"
                disabled={columns.length === 0}
                onClick={() => onChange([])}
              >
                Hide all
              </Button>
            )}
          </span>
        </div>
        {columns.length === 0 ? (
          <p className="rounded-md border border-dashed border-border px-3 py-4 text-sm text-fg-muted">
            No columns shown yet. Pick some below.
          </p>
        ) : (
          <div className="max-h-64 overflow-y-auto rounded-md border border-border bg-canvas">
            <SortableList
              label="Shown columns"
              items={columns}
              getKey={(c) => c}
              getLabel={label}
              moveButtons="always"
              onReorder={(next) => onChange(next)}
              renderItem={(col) => (
                <label className="flex cursor-pointer select-none items-center gap-2 px-2 py-2 text-sm text-fg">
                  <Checkbox
                    checked
                    aria-label={`Show ${label(col)}`}
                    onChange={() => onChange(columns.filter((c) => c !== col))}
                  />
                  {label(col)}
                </label>
              )}
            />
          </div>
        )}
      </section>

      <section className="space-y-1.5">
        <h4 className="text-sm font-semibold text-fg">Not shown</h4>
        <Input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Find a column to add…"
          aria-label="Find a column to add"
          className="w-full"
        />
        <div className="max-h-64 space-y-3 overflow-y-auto rounded-md border border-border bg-canvas p-2">
          {notShown.length === 0 && (
            <p className="px-1 py-2 text-sm text-fg-muted">
              {wanted ? 'Nothing matches.' : 'Every column is shown.'}
            </p>
          )}
          {notShown.map((g) => (
            <div key={g.title ?? ''}>
              {g.title && (
                <h5 className="mb-1 px-1 text-xs font-medium text-fg-subtle">
                  {g.title}
                </h5>
              )}
              {g.items.map((i) => (
                <label
                  key={i.value}
                  onClick={range.onClick}
                  className="flex cursor-pointer select-none items-center gap-2 rounded px-2 py-1.5 text-sm text-fg hover:bg-canvas-subtle"
                >
                  <Checkbox
                    checked={false}
                    aria-label={`Show ${i.label}`}
                    onClick={range.onClick}
                    onChange={() => add(i.value)}
                  />
                  {i.label}
                </label>
              ))}
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
