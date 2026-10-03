import { useRef, useState } from 'react'
import { Link } from 'react-router'
import type { CivexRecord } from '../../api/records'
import type { Field } from '../../api/schemas'
import { toInputProps } from '../../utils/restrictions'
import { Chip, IconButton, Input, ListButton } from '../ui'
import { Plus, X } from '../ui/icons'
import { recordLabel, useRecordSearch } from './RecordSearchPicker'
import { CollectionMarker } from './CollectionMarker'
import { useCollectionName } from './timeZoneContext'

/** Reference / reference_list values as removable bubbles, with an inline
 * search to add more. Every change is saved straight away (`onSave`).
 *
 * Keyboard: Backspace or Delete on a focused bubble removes it (focus moves
 * to its neighbour); Backspace in an empty search removes the last one;
 * arrows and Enter pick from the results; Escape closes the search. */
export function ReferenceChips({
  field,
  value,
  labels,
  collections,
  onSave,
}: {
  field: Field
  value: unknown
  /** id -> natural name, as the server resolved them for this record. */
  labels?: Record<string, string | null> | null
  /** id -> collection name, for targets outside the record's own collection. */
  collections?: Record<string, string> | null
  onSave: (value: unknown | undefined) => void
}) {
  const multiple = field.type === 'reference_list'
  const ids: string[] = multiple
    ? Array.isArray(value)
      ? (value as string[])
      : []
    : typeof value === 'string' && value
      ? [value]
      : []
  const schemaName = toInputProps(field).targetSchema ?? ''
  const root = useRef<HTMLDivElement>(null)
  const [adding, setAdding] = useState(false)
  const [search, setSearch] = useState('')
  const [active, setActive] = useState(0)
  // Labels of records picked this session, until the server's own arrive.
  const [picked, setPicked] = useState<Record<string, string>>({})
  const { results, loading } = useRecordSearch(schemaName, adding ? search : '')
  const options = results.filter((r) => !ids.includes(r.id))

  const currentCollection = useCollectionName()
  // Records picked this session carry their own collection until the
  // server's reference_collections arrive.
  const [pickedFrom, setPickedFrom] = useState<Record<string, string>>({})
  const collectionOf = (id: string) => collections?.[id] ?? pickedFrom[id]

  const labelOf = (id: string) => labels?.[id] ?? picked[id] ?? id.slice(0, 8)

  function save(next: string[]) {
    onSave(multiple ? (next.length ? next : undefined) : next[0])
  }
  const focusAdd = () =>
    setTimeout(
      () => root.current?.querySelector<HTMLElement>('[data-add]')?.focus(),
      0,
    )

  function remove(index: number) {
    save(ids.filter((_, i) => i !== index))
    // the neighbour, else the add button
    setTimeout(() => {
      const chips = root.current?.querySelectorAll<HTMLElement>('[data-chip]')
      const next = chips?.[Math.min(index, (chips?.length ?? 1) - 1)]
      if (next && chips && chips.length > 0) next.focus()
      else root.current?.querySelector<HTMLElement>('[data-add]')?.focus()
    }, 0)
  }

  function choose(record: CivexRecord) {
    setPicked((p) => ({ ...p, [record.id]: recordLabel(record) }))
    if (record.collection && record.collection !== currentCollection)
      setPickedFrom((p) => ({ ...p, [record.id]: record.collection! }))
    save(multiple ? [...ids, record.id] : [record.id])
    setSearch('')
    setActive(0)
    if (!multiple) {
      setAdding(false)
      focusAdd()
    }
  }

  function closeSearch() {
    setAdding(false)
    setSearch('')
    setActive(0)
  }

  return (
    <div
      ref={root}
      className="flex flex-wrap items-center gap-1.5"
      onBlur={(e) => {
        if (adding && !e.currentTarget.contains(e.relatedTarget)) closeSearch()
      }}
    >
      {ids.map((id, i) => (
        <span
          key={id}
          data-chip
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === 'Backspace' || e.key === 'Delete') {
              e.preventDefault()
              remove(i)
            }
          }}
          className="inline-flex items-center gap-1 rounded-full border border-accent-muted bg-accent-subtle py-0.5 pl-3 pr-1 text-sm font-medium text-accent focus-visible:outline-2 focus-visible:outline-accent"
        >
          <Link to={`/records/${id}`} className="hover:underline" tabIndex={-1}>
            {labelOf(id)}
          </Link>
          {collectionOf(id) && <CollectionMarker name={collectionOf(id)!} />}
          <IconButton
            icon={X}
            size="xs"
            tabIndex={-1}
            onClick={() => remove(i)}
            aria-label={`Remove ${labelOf(id)}`}
            iconProps={{ size: 12 }}
          />
        </span>
      ))}

      {adding ? (
        <div className="relative min-w-[12rem] flex-1">
          <Input
            autoFocus
            type="text"
            value={search}
            aria-label={`Search ${schemaName || 'records'}`}
            placeholder={`Search ${schemaName || 'records'}…`}
            className="w-full"
            onChange={(e) => {
              setSearch(e.target.value)
              setActive(0)
            }}
            onKeyDown={(e) => {
              if (e.key === 'Escape') {
                e.stopPropagation()
                closeSearch()
                focusAdd()
              } else if (e.key === 'ArrowDown') {
                e.preventDefault()
                setActive((a) => Math.min(a + 1, options.length - 1))
              } else if (e.key === 'ArrowUp') {
                e.preventDefault()
                setActive((a) => Math.max(a - 1, 0))
              } else if (e.key === 'Enter') {
                e.preventDefault()
                if (options[active]) choose(options[active])
              } else if (e.key === 'Backspace' && !search && ids.length) {
                remove(ids.length - 1)
              }
            }}
          />
          <div
            role="listbox"
            className="absolute z-10 mt-1 max-h-48 w-full overflow-y-auto rounded-md border border-border bg-canvas text-sm shadow-sm"
          >
            {loading && <div className="px-3 py-2 text-fg-muted">Loading…</div>}
            {!loading && options.length === 0 && (
              <div className="px-3 py-2 italic text-fg-muted">
                No records found
              </div>
            )}
            {options.map((r, i) => (
              <ListButton
                key={r.id}
                role="option"
                aria-selected={i === active}
                active={i === active}
                tabIndex={-1}
                onMouseDown={(e) => {
                  e.preventDefault()
                  choose(r)
                }}
                onMouseEnter={() => setActive(i)}
                className="truncate"
              >
                <span className="text-fg">{recordLabel(r)}</span>
                {r.collection && r.collection !== currentCollection && (
                  <CollectionMarker name={r.collection} />
                )}
                <span className="ml-2 font-mono text-xs text-fg-muted">
                  {r.id.slice(0, 8)}
                </span>
              </ListButton>
            ))}
          </div>
        </div>
      ) : (
        <Chip dashed onClick={() => setAdding(true)} data-add="">
          <Plus size={12} />
          {ids.length === 0 ? 'Add' : multiple ? 'Add more' : 'Change'}
        </Chip>
      )}
    </div>
  )
}
