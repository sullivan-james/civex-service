import { useState } from 'react'
import { Button, Disclosure, IconButton } from '../ui'
import type { RecordSelectionBody } from '../../api/records'
import { ChartView } from '../charts/ChartView'
import { fieldKey } from '../../utils/summary'
import { Plus, X } from '../ui/icons'
import { FilterBuilder } from '../views/FilterBuilder'
import {
  addChildById,
  emptyCondition,
  toWireFilterTree,
  wireToRootGroup,
  type FilterGroupNode,
  type FilterTreeWire,
} from '../../utils/filterTree'
import {
  describeTree,
  referenceIdsIn,
  topLevelTerms,
  withoutTerm,
} from '../../utils/filterLabels'
import type { FilterableField } from '../../utils/hierarchy'
import { useRecordLabels } from './useRecordLabels'

const same = (a: FilterTreeWire | null, b: FilterTreeWire | null) =>
  JSON.stringify(a) === JSON.stringify(b)

/** A tree to edit: the filter as it stands, or one blank condition when
 * there is none, so opening the editor never shows an empty box. */
function editableRoot(wire: FilterTreeWire | null): FilterGroupNode {
  const root = wireToRootGroup(wire)
  return root.children.length > 0
    ? root
    : addChildById(root, root.id, emptyCondition())
}

/** The editor behind the "+ Filter" button. Holds the half-built tree itself
 * (an unfinished condition has no wire form yet) and pushes every complete
 * change up. The filter can also change from outside while it is open -- a
 * chip removed, a saved filter applied, Back -- and the tree follows. */
function FilterEditor({
  wire,
  fields,
  records,
  onChange,
}: {
  wire: FilterTreeWire | null
  fields: FilterableField[]
  records?: RecordSelectionBody
  onChange: (wire: FilterTreeWire | null) => void
}) {
  const [root, setRoot] = useState<FilterGroupNode>(() => editableRoot(wire))
  // The filter this tree last agreed with: what the editor emitted, or what
  // came in. A new `wire` that isn't that is somebody else's change.
  const [agreed, setAgreed] = useState(wire)
  const [seen, setSeen] = useState(wire)
  if (!same(wire, seen)) {
    setSeen(wire)
    if (!same(wire, agreed)) {
      setAgreed(wire)
      setRoot(editableRoot(wire))
    }
  }
  return (
    <div className="space-y-2">
      <FilterBuilder
        root={root}
        fields={fields}
        // A field's values with how many of the listed records hold each:
        // the charts' own view, asked for only once it is opened, and its
        // rows pick values in this same filter.
        values={
          records &&
          ((field) => (
            <Disclosure summary="Values">
              <div className="p-2">
                <ChartView
                  chart={{
                    id: `values-${fieldKey(field)}`,
                    group_by: [fieldKey(field)],
                    measures: ['count'],
                  }}
                  records={records}
                  fields={fields}
                  onFilter={onChange}
                />
              </div>
            </Disclosure>
          ))
        }
        onChange={(next) => {
          const emitted = toWireFilterTree(next)
          setRoot(next)
          setAgreed(emitted)
          onChange(emitted)
        }}
      />
    </div>
  )
}

/** The filter as removable chips, plus an editor that opens in the page
 * beneath them. It is part of the layout, not a floating panel, so however
 * many conditions there are it grows downward and never leaves the screen. */
export function FilterControls({
  wire,
  fields,
  listedSchema,
  records,
  addLabel = 'Filter',
  onChange,
}: {
  wire: FilterTreeWire | null
  fields: FilterableField[]
  listedSchema: string
  /** What the button that opens the builder says. */
  addLabel?: string
  /** The records listed: with it, a condition on a field of choices shows
   * how many of them hold each value. */
  records?: RecordSelectionBody
  onChange: (wire: FilterTreeWire | null) => void
}) {
  const [open, setOpen] = useState(false)
  const terms = topLevelTerms(wire)
  const labels = useRecordLabels(referenceIdsIn(wire, fields))
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        {terms.map((term, i) => {
          const label = describeTree(term, fields, listedSchema, labels)
          return (
            <span
              key={`${i}-${label}`}
              className="inline-flex max-w-full items-center gap-1 rounded-md bg-accent-subtle pl-3 pr-1 py-1 text-sm text-accent"
            >
              <span className="min-w-0 break-words">{label}</span>
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
        <Button
          size="sm"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-controls="explorer-filter-editor"
          className="border-dashed"
        >
          {open ? (
            'Done'
          ) : (
            <>
              <Plus size={12} /> {addLabel}
            </>
          )}
        </Button>
        {terms.length > 0 && (
          <Button size="sm" variant="ghost" onClick={() => onChange(null)}>
            Clear filters
          </Button>
        )}
      </div>
      {open && (
        <section
          id="explorer-filter-editor"
          aria-label="Edit filters"
          className="rounded-md border border-border bg-canvas-subtle p-3"
        >
          <FilterEditor
            wire={wire}
            fields={fields}
            records={records}
            onChange={onChange}
          />
        </section>
      )}
    </div>
  )
}
