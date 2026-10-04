import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { recordsApi, type CivexRecord } from '../api/records'
import { useCollections } from '../hooks/useCollections'
import { usePins, useRecents } from '../hooks/usePins'
import { useSchemas } from '../hooks/useSchemas'
import { useAllViews } from '../hooks/useViews'
import { buildGroups } from '../utils/paletteSearch'
import {
  collectionTarget,
  placeTarget,
  recordTarget,
  viewTarget,
} from '../utils/navTargets'
import type { NavTarget } from '../utils/pins'
import { displayLabel } from '../utils/naming'
import { PIN_ICONS } from './pinIcons'
import { IconButton } from './ui/IconButton'
import { Modal, ModalHeader } from './ui/Modal'
import { Search, Star } from './ui/icons'

const MIN_RECORD_QUERY = 2
const NO_RECORDS: CivexRecord[] = []

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return debounced
}

/** Ctrl+K: jump to a collection, schema, saved filter, record or place by
 * typing; with nothing typed, the pinned and recent things. A star on any
 * result pins it. Mounted only while open, so its queries run only then. */
export function CommandPalette({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate()
  const listId = useId()
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const listRef = useRef<HTMLDivElement>(null)

  const { pins, isPinned, toggle } = usePins()
  const recents = useRecents()
  const { data: collections } = useCollections()
  const { data: schemas } = useSchemas()
  const { data: views } = useAllViews()

  // One request for records of every schema and collection, once the
  // person has paused typing.
  const recordQuery = useDebounced(query.trim(), 250)
  const recordSearch = useQuery({
    queryKey: ['palette-records', recordQuery],
    queryFn: () => recordsApi.search(recordQuery, 8),
    enabled: recordQuery.length >= MIN_RECORD_QUERY,
    staleTime: 10_000,
  })
  const foundRecords = recordSearch.data ?? NO_RECORDS

  const groups = useMemo(
    () =>
      buildGroups(query, {
        pins,
        recents,
        collections: (collections ?? []).map(collectionTarget),
        schemas: (schemas ?? []).map((s) => ({
          ...placeTarget(
            `/schemas/${s.id}/records`,
            displayLabel(s.name, s.label),
            'Schema',
          ),
        })),
        views: (views ?? []).map((v) =>
          viewTarget({ id: v.schema_id, name: v.schema_name }, v.name),
        ),
        records:
          recordQuery.length >= MIN_RECORD_QUERY
            ? foundRecords.map(recordTarget)
            : [],
      }),
    [
      query,
      pins,
      recents,
      collections,
      schemas,
      views,
      recordQuery,
      foundRecords,
    ],
  )
  const flat = groups.flatMap((g) => g.items)

  // A new result set starts at its first row.
  const [seenSet, setSeenSet] = useState('')
  const setKey = flat.map((t) => t.key).join('|')
  if (setKey !== seenSet) {
    setSeenSet(setKey)
    setActive(0)
  }

  useEffect(() => {
    listRef.current
      ?.querySelector('[aria-selected="true"]')
      ?.scrollIntoView?.({ block: 'nearest' })
  }, [active, setKey])

  function open(target: NavTarget) {
    onClose()
    navigate(target.to)
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((i) => Math.min(i + 1, flat.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((i) => Math.max(i - 1, 0))
    } else if (e.key === 'Enter' && flat[active]) {
      e.preventDefault()
      open(flat[active])
    }
  }

  const searching = recordSearch.isFetching
  let index = -1
  return (
    <Modal onClose={onClose} size="lg" className="self-start mt-[10vh]">
      <ModalHeader onClose={onClose}>Jump to</ModalHeader>
      <div className="flex items-center gap-3 border-b border-border px-4 py-3">
        <Search size={16} className="shrink-0 text-fg-subtle" aria-hidden />
        <input
          autoFocus
          role="combobox"
          aria-expanded="true"
          aria-controls={listId}
          aria-activedescendant={
            flat[active] ? `${listId}-${active}` : undefined
          }
          aria-label="Jump to a collection, schema, filter or record"
          placeholder="Jump to a collection, schema, filter or record…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
          className="min-w-0 flex-1 bg-transparent text-sm text-fg outline-none placeholder:text-fg-subtle"
        />
        <kbd className="rounded-md border border-border px-1.5 text-xs text-fg-muted">
          Esc
        </kbd>
      </div>
      <div
        ref={listRef}
        id={listId}
        role="listbox"
        aria-label="Results"
        className="max-h-[60vh] overflow-y-auto py-2"
      >
        {groups.length === 0 ? (
          <p className="px-4 py-6 text-center text-sm text-fg-muted">
            {query.trim()
              ? searching
                ? 'Searching…'
                : `Nothing matches “${query.trim()}”.`
              : 'Nothing pinned or opened yet. Start typing to search.'}
          </p>
        ) : (
          groups.map((group) => (
            <div key={group.heading} role="group" aria-label={group.heading}>
              <div className="px-4 pb-1 pt-2 text-xs font-semibold uppercase tracking-wider text-fg-subtle">
                {group.heading}
              </div>
              {group.items.map((item) => {
                index += 1
                const i = index
                const Icon = PIN_ICONS[item.kind]
                const pinned = isPinned(item.key)
                return (
                  <div
                    key={item.key}
                    id={`${listId}-${i}`}
                    role="option"
                    aria-selected={i === active}
                    onMouseMove={() => setActive(i)}
                    onClick={() => open(item)}
                    className={`flex cursor-pointer items-center gap-3 px-4 py-1.5 text-sm ${
                      i === active ? 'bg-accent-subtle' : ''
                    }`}
                  >
                    <Icon
                      size={16}
                      className="shrink-0 text-fg-subtle"
                      aria-hidden="true"
                    />
                    <span className="min-w-0 truncate font-medium text-fg">
                      {item.label}
                    </span>
                    {item.context && (
                      <span className="truncate text-xs text-fg-subtle">
                        {item.context}
                      </span>
                    )}
                    <IconButton
                      icon={Star}
                      tabIndex={-1}
                      className={`ml-auto ${pinned ? '!text-accent' : ''}`}
                      aria-label={
                        pinned ? `Unpin ${item.label}` : `Pin ${item.label}`
                      }
                      aria-pressed={pinned}
                      iconProps={{ fill: pinned ? 'currentColor' : 'none' }}
                      onClick={(e) => {
                        e.stopPropagation()
                        toggle(item)
                      }}
                    />
                  </div>
                )
              })}
            </div>
          ))
        )}
      </div>
    </Modal>
  )
}
