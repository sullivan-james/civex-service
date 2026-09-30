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
      <h2 className="hidden md:block px-2 pt-1 pb-2 text-xs font-bold uppercase tracking-wider text-fg border-b border-border mb-1">
        Hierarchy
      </h2>
      {levels.map(({ schema, depth, count }) => {
        const active = schema.name === current
        return (
          <button
            key={schema.id}
            type="button"
            onClick={() => onPick(schema)}
            aria-current={active ? 'true' : undefined}
            style={{ paddingLeft: `${0.5 + depth}rem` }}
            className={`flex items-center justify-between gap-2 whitespace-nowrap rounded-md py-2 pr-2 text-sm cursor-pointer transition-colors ${
              active
                ? 'bg-accent-subtle text-accent-emphasis font-semibold'
                : 'text-fg hover:bg-canvas-inset'
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
          </button>
        )
      })}
    </nav>
  )
}
