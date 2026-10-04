import { useMemo } from 'react'
import { useRangeSelect } from '../../hooks/useRangeSelect'
import { useSchemas } from '../../hooks/useSchemas'
import { Checkbox, Field, Select } from '../ui'
import { displayLabel } from '../../utils/naming'
import type { CollectionScope } from '../../api/collections'
import type { Schema } from '../../api/schemas'

interface Props {
  scope: CollectionScope
  onScopeChange: (scope: CollectionScope) => void
  /** Names of the enabled schemas. */
  schemas: string[]
  onSchemasChange: (schemas: string[]) => void
}

/** A child schema's parent record lives in the same collection, so the
 * parent has to be enabled too: ticking a child ticks its ancestors, and
 * unticking a parent unticks its descendants. */
function toggled(
  all: Schema[],
  selected: Set<string>,
  schema: Schema,
  on: boolean,
): string[] {
  const byId = new Map(all.map((s) => [s.id, s]))
  const next = new Set(selected)
  if (on) {
    for (
      let s: Schema | undefined = schema;
      s;
      s = s.parent_id ? byId.get(s.parent_id) : undefined
    )
      next.add(s.name)
  } else {
    const removing = new Set([schema.id])
    for (let grew = true; grew;) {
      grew = false
      for (const s of all)
        if (s.parent_id && removing.has(s.parent_id) && !removing.has(s.id)) {
          removing.add(s.id)
          grew = true
        }
    }
    for (const s of all) if (removing.has(s.id)) next.delete(s.name)
  }
  return [...next].sort()
}

/** Scope and schema-list inputs, shared by the create and edit forms. */
export function CollectionScopeFields({
  scope,
  onScopeChange,
  schemas,
  onSchemasChange,
}: Props) {
  const { data: allSchemas } = useSchemas()
  const live = useMemo(
    () => (allSchemas ?? []).filter((s) => !s.deleted_at),
    [allSchemas],
  )
  const selected = useMemo(() => new Set(schemas), [schemas])
  const range = useRangeSelect(live.map((s) => s.name))

  /** One box, or -- with shift -- every schema from the last one clicked to this
   * one, each going through the same parent/child rule as a single click. */
  function setSchema(schema: Schema, on: boolean) {
    const ids = range.rangeFor(schema.name)
    if (!ids) return onSchemasChange(toggled(live, selected, schema, on))
    let next = selected
    for (const s of live.filter((x) => ids.includes(x.name)))
      next = new Set(toggled(live, next, s, on))
    onSchemasChange([...next].sort())
  }

  return (
    <>
      <Field
        label="Scope"
        info="Local: only records in this collection can reference its records. Global: records in any collection can — use it for shared reference data such as species or sites."
      >
        <Select
          value={scope}
          onChange={(e) => onScopeChange(e.target.value as CollectionScope)}
          className="w-full"
        >
          <option value="local">Local — private to this collection</option>
          <option value="global">Global — referenceable from anywhere</option>
        </Select>
      </Field>
      <Field
        label="Schemas"
        info="The schemas this collection is for. Its records can only be of these. A child schema needs its parent schema too."
      >
        {live.length === 0 ? (
          <p className="text-sm text-fg-muted">
            No schemas yet — create one first.
          </p>
        ) : (
          <ul className="max-h-48 space-y-1 overflow-y-auto rounded-md border border-border p-2">
            {live.map((s) => (
              <li key={s.id}>
                <label
                  onClick={range.onClick}
                  className="flex cursor-pointer select-none items-center gap-2 text-sm"
                >
                  <Checkbox
                    checked={selected.has(s.name)}
                    onClick={range.onClick}
                    onChange={(e) => setSchema(s, e.target.checked)}
                  />
                  <span className={s.parent_id ? 'pl-4' : ''}>
                    {displayLabel(s.name, s.label)}
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}
      </Field>
    </>
  )
}
