import { Field, Input } from '../ui'
import { FilterControls } from '../explorer/FilterControls'
import { useDebouncedSearch } from '../../hooks/useDebouncedSearch'
import type { FilterableField } from '../../utils/hierarchy'
import type { TableState } from '../../utils/tableState'

/** Search box and filter chips over a table, driven by `useTableState`. The
 * filter editor is the record explorer's own, so filtering feels the same
 * wherever a list is. Leave `searchLabel` out where the table has no text
 * search. */
export function TableControls({
  state,
  patch,
  fields,
  searchLabel,
}: {
  state: TableState
  patch: (p: Partial<TableState>) => void
  fields: FilterableField[]
  searchLabel?: string
}) {
  const [text, setText] = useDebouncedSearch(state.q, (q) => patch({ q }))
  return (
    <div className="space-y-2">
      {searchLabel && (
        <div className="max-w-xl">
          <Field label={searchLabel} hideLabel>
            <Input
              type="search"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={searchLabel}
              className="w-full"
            />
          </Field>
        </div>
      )}
      <FilterControls
        wire={state.filter}
        fields={fields}
        listedSchema=""
        onChange={(filter) => patch({ filter })}
      />
    </div>
  )
}
