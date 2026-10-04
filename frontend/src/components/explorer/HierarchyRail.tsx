import { ListButton } from '../ui'
import type { Schema } from '../../api/schemas'
import { displayLabel } from '../../utils/naming'

export interface RailLevel {
  schema: Schema
  /** Nesting below the scope root, for indentation. */
  depth: number
  /** Records of this schema in scope; null for a level at or above the
   * scope (the record you are inside of, and its parents). */
  count: number | null
}

/** The schema hierarchy as a column of levels -- encounter, recording,
 * selection -- each with how many records sit in the current scope. Picking
 * one lists that schema's records. Indented per nesting level; the level
 * being listed is highlighted and its count pill filled. */
export function HierarchyRail({
  levels,
  current,
  onPick,
}: {
  levels: RailLevel[]
  current: string | null
  onPick: (schema: Schema) => void
}) {
  return (
    <nav
      aria-label="Data hierarchy"
      className="md:w-60 shrink-0 md:sticky md:top-4 flex md:flex-col gap-1 overflow-x-auto rounded-md border border-border bg-canvas-subtle p-2"
    >
      <h2 className="mb-1 hidden border-b border-border px-2 pb-2 pt-1 text-sm font-semibold text-fg md:block">
        Hierarchy
      </h2>
      {levels.map(({ schema, depth, count }) => {
        const active = schema.name === current
        return (
          <ListButton
            key={schema.id}
            onClick={() => onPick(schema)}
            active={active}
            aria-current={active ? 'true' : undefined}
            style={{ paddingLeft: `${0.75 + depth}rem` }}
            className={`flex items-center justify-between gap-2 whitespace-nowrap rounded-md ${
              active ? 'font-semibold text-accent-emphasis' : 'text-fg'
            }`}
          >
            <span>{displayLabel(schema.name, schema.label)}</span>
            {count !== null && (
              <span
                className={`rounded-full px-2 font-mono text-xs ${
                  active
                    ? 'bg-accent text-fg-on-emphasis'
                    : 'bg-canvas-inset text-fg-muted'
                }`}
              >
                {count.toLocaleString()}
              </span>
            )}
          </ListButton>
        )
      })}
    </nav>
  )
}
