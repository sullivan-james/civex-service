import { useRangeSelect } from '../../hooks/useRangeSelect'
import { Checkbox, IconButton, Subheading } from '../ui'
import { ChevronUp, ChevronDown, X } from '../ui/icons'
import { displayLabel } from '../../utils/naming'
import type { ResolvedField } from '../../utils/viewFields'
import type { JoinableColumn } from '../../utils/viewFields'

interface ColumnPickerProps {
  columns: string[]
  onChange: (columns: string[]) => void
  baseFields: ResolvedField[]
  joinable: JoinableColumn[]
}

export function columnLabel(
  col: string,
  baseFields: ResolvedField[],
  joinable: JoinableColumn[],
): string {
  if (!col.includes('.')) {
    const field = baseFields.find((f) => f.name === col)
    return field ? displayLabel(field.name, field.label) : col
  }
  const join = joinable.find((j) => j.value === col)
  return join ? join.label : col
}

/** Base schema fields (own + inherited) plus one hop of reference-field
 * joins -- toggled on the left, ordered on the right. */
export function ColumnPicker({
  columns,
  onChange,
  baseFields,
  joinable,
}: ColumnPickerProps) {
  const joinsByRef = new Map<string, JoinableColumn[]>()
  for (const join of joinable) {
    const key = join.refField.name
    joinsByRef.set(key, [...(joinsByRef.get(key) ?? []), join])
  }

  // Every box in the order drawn: the fields, then each reference's columns.
  const shown = [
    ...baseFields.map((f) => f.name),
    ...[...joinsByRef.values()].flatMap((joins) => joins.map((j) => j.value)),
  ]
  const range = useRangeSelect(shown)

  function toggle(col: string) {
    // Shift-click: everything from the last box clicked to this one takes the
    // state this one is going to.
    const ids = range.rangeFor(col)
    const on = !columns.includes(col)
    if (!ids) {
      onChange(on ? [...columns, col] : columns.filter((c) => c !== col))
      return
    }
    onChange(
      on
        ? [...columns, ...ids.filter((c) => !columns.includes(c))]
        : columns.filter((c) => !ids.includes(c)),
    )
  }

  function move(index: number, direction: 'up' | 'down') {
    const target = direction === 'up' ? index - 1 : index + 1
    if (target < 0 || target >= columns.length) return
    const next = [...columns]
    ;[next[index], next[target]] = [next[target], next[index]]
    onChange(next)
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div className="border border-border rounded-md p-3 max-h-80 overflow-y-auto">
        <Subheading className="mb-2">Available columns</Subheading>
        <div className="flex flex-col gap-1">
          {baseFields.map((field) => (
            <label
              key={field.name}
              onClick={range.onClick}
              className="flex items-center gap-2 text-sm text-fg cursor-pointer select-none py-0.5"
            >
              <Checkbox
                checked={columns.includes(field.name)}
                onClick={range.onClick}
                onChange={() => toggle(field.name)}
              />
              {displayLabel(field.name, field.label)}
            </label>
          ))}
        </div>

        {joinsByRef.size > 0 && (
          <div className="mt-3 flex flex-col gap-3">
            {[...joinsByRef.entries()].map(([refName, joins]) => (
              <div key={refName}>
                <h4 className="text-xs font-medium text-fg-subtle mb-1">
                  via {displayLabel(refName, joins[0].refField.label)}
                </h4>
                <div className="flex flex-col gap-1 pl-2">
                  {joins.map((join) => (
                    <label
                      key={join.value}
                      onClick={range.onClick}
                      className="flex items-center gap-2 text-sm text-fg cursor-pointer select-none py-0.5"
                    >
                      <Checkbox
                        checked={columns.includes(join.value)}
                        onClick={range.onClick}
                        onChange={() => toggle(join.value)}
                      />
                      {displayLabel(
                        join.targetField.name,
                        join.targetField.label,
                      )}
                    </label>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="border border-border rounded-md p-3 max-h-80 overflow-y-auto">
        <Subheading as="h3">Selected columns</Subheading>
        {columns.length === 0 ? (
          <p className="text-sm text-fg-subtle italic">
            No columns selected yet — pick some on the left.
          </p>
        ) : (
          <ul className="flex flex-col gap-1">
            {columns.map((col, index) => (
              <li
                key={col}
                className="flex items-center gap-2 text-sm text-fg bg-canvas-subtle rounded-md px-2 py-1"
              >
                <span className="flex-1 truncate">
                  {columnLabel(col, baseFields, joinable)}
                </span>
                <IconButton
                  icon={ChevronUp}
                  aria-label={`Move ${col} earlier`}
                  variant="subtle"
                  size="sm"
                  disabled={index === 0}
                  onClick={() => move(index, 'up')}
                />
                <IconButton
                  icon={ChevronDown}
                  aria-label={`Move ${col} later`}
                  variant="subtle"
                  size="sm"
                  disabled={index === columns.length - 1}
                  onClick={() => move(index, 'down')}
                />
                <IconButton
                  icon={X}
                  aria-label={`Remove ${col}`}
                  variant="subtle"
                  size="sm"
                  onClick={() => toggle(col)}
                />
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
