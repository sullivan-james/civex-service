import { Button } from './Button'
import { CheckRow } from './CheckRow'
import { TriggerPopover } from './TriggerPopover'
import { ChevronDown } from './icons'

export interface MultiPickOption {
  value: string
  label: string
  /** Shown after the label, e.g. how many there are. */
  hint?: string
}

/** A dropdown of choices any number of which can be on: the list toolbar's
 * pick, for when one at a time isn't enough. Nothing ticked means all. The
 * button says what is chosen. Built from the shared popover and `CheckRow`. */
export function MultiPick({
  label,
  options,
  value,
  onChange,
}: {
  label: string
  options: MultiPickOption[]
  value: string[]
  onChange: (next: string[]) => void
}) {
  const chosen = options.filter((o) => value.includes(o.value))
  const summary =
    chosen.length === 0
      ? `${label}: all`
      : chosen.length === 1
        ? `${label}: ${chosen[0].label}`
        : `${label}: ${chosen.length} chosen`
  return (
    <TriggerPopover
      label={label}
      panelClassName="w-72 space-y-1 rounded-md border border-border bg-canvas p-2 shadow-lg"
      trigger={({ open, toggle }) => (
        <Button size="sm" aria-expanded={open} onClick={toggle}>
          {summary}
          <ChevronDown size={14} aria-hidden="true" />
        </Button>
      )}
    >
      {options.map((o) => (
        <CheckRow
          key={o.value}
          compact
          title={o.hint ? `${o.label} (${o.hint})` : o.label}
          checked={value.includes(o.value)}
          onChange={(on) =>
            onChange(
              on ? [...value, o.value] : value.filter((v) => v !== o.value),
            )
          }
        />
      ))}
      {value.length > 0 && (
        <Button size="sm" variant="link" onClick={() => onChange([])}>
          All of them
        </Button>
      )}
    </TriggerPopover>
  )
}
