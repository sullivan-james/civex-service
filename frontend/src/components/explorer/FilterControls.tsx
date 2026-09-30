import { useState } from 'react'
import { Button, IconButton, TriggerPopover } from '../ui'
import { Plus, X } from '../ui/icons'
import { FilterBuilder } from '../views/FilterBuilder'
import {
  toWireFilterTree,
  wireToRootGroup,
  type FilterGroupNode,
  type FilterTreeWire,
} from '../../utils/filterTree'
import {
  describeTree,
  topLevelTerms,
  withoutTerm,
} from '../../utils/filterLabels'
import type { FilterableField } from '../../utils/hierarchy'

/** The editor behind the "+ Filter" button. Holds the half-built tree itself
 * (an unfinished condition has no wire form yet) and pushes every complete
 * change up; it is mounted fresh each time the popover opens. */
function FilterEditor({
  wire,
  fields,
  onChange,
}: {
  wire: FilterTreeWire | null
  fields: FilterableField[]
  onChange: (wire: FilterTreeWire | null) => void
}) {
  const [root, setRoot] = useState<FilterGroupNode>(() => wireToRootGroup(wire))
  return (
    <div className="w-[34rem] max-w-[90vw] space-y-2">
      <p className="text-xs text-fg-muted">
        Match on this level, on a parent record, or on any child record — for
        example selections in a recording whose selection_table is empty.
      </p>
      <FilterBuilder
        root={root}
        fields={fields}
        onChange={(next) => {
          setRoot(next)
          onChange(toWireFilterTree(next))
        }}
      />
    </div>
  )
}

/** The filter as removable chips plus the popover that edits it. */
export function FilterControls({
  wire,
  fields,
  listedSchema,
  onChange,
}: {
  wire: FilterTreeWire | null
  fields: FilterableField[]
  listedSchema: string
  onChange: (wire: FilterTreeWire | null) => void
}) {
  const terms = topLevelTerms(wire)
  return (
    <div className="flex flex-wrap items-center gap-2">
      {terms.map((term, i) => {
        const label = describeTree(term, fields, listedSchema)
        return (
          <span
            key={`${i}-${label}`}
            className="inline-flex items-center gap-1 rounded-md bg-accent-subtle pl-3 pr-1 py-1 text-sm text-accent"
          >
            {label}
            <IconButton
              icon={X}
              size="sm"
              variant="subtle"
              aria-label={`Remove filter ${label}`}
              onClick={() => onChange(withoutTerm(wire, i))}
            />
          </span>
        )
      })}
      <TriggerPopover
        label="Edit filters"
        trigger={({ toggle, open }) => (
          <Button
            size="sm"
            onClick={toggle}
            aria-expanded={open}
            className="border-dashed"
          >
            <Plus size={12} /> Filter
          </Button>
        )}
      >
        <FilterEditor wire={wire} fields={fields} onChange={onChange} />
      </TriggerPopover>
    </div>
  )
}
