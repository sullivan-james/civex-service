import { useEffect, useMemo, useState } from 'react'
import { recordsApi, type CivexRecord } from '../../api/records'
import { Chip, IconButton, Input, ListButton } from '../ui'
import { CollectionMarker } from './CollectionMarker'
import { useCollectionName } from './timeZoneContext'
import { X } from '../ui/icons'

export function recordLabel(r: CivexRecord): string {
  return r.natural_name ?? r.id.slice(0, 8)
}

/** Debounced schema-scoped record search, shared by the single- and multi-select pickers below. */
export function useRecordSearch(schemaName: string, search: string) {
  const [results, setResults] = useState<CivexRecord[]>([])
  const [loading, setLoading] = useState(false)
  // Only what a record in this collection may reference: its own and global
  // collections' records, never another local collection's.
  const reachableFrom = useCollectionName() ?? undefined

  useEffect(() => {
    if (!schemaName) return
    // `stale` drops the response of a superseded search so a slow earlier
    // request can't overwrite the results of a newer one.
    let stale = false
    const timer = setTimeout(async () => {
      setLoading(true)
      try {
        const records = await recordsApi.searchBySchema(
          schemaName,
          search || undefined,
          undefined,
          reachableFrom,
        )
        if (!stale) setResults(records)
      } finally {
        if (!stale) setLoading(false)
      }
    }, 250)
    return () => {
      stale = true
      clearTimeout(timer)
    }
  }, [schemaName, search, reachableFrom])

  return { results, loading }
}

function ResultsDropdown({
  currentCollection,
  loading,
  results,
  emptyMessage,
  isSelected,
  onSelect,
}: {
  currentCollection: string | null
  loading: boolean
  results: CivexRecord[]
  emptyMessage: string
  isSelected: (id: string) => boolean
  onSelect: (record: CivexRecord) => void
}) {
  return (
    <div className="absolute z-30 mt-1 w-full bg-canvas border border-border rounded-md shadow-sm max-h-48 overflow-y-auto text-sm">
      {loading && <div className="px-3 py-2 text-fg-muted">Loading…</div>}
      {!loading && results.length === 0 && (
        <div className="px-3 py-2 text-fg-muted italic">{emptyMessage}</div>
      )}
      {results.map((record) => (
        <ListButton
          key={record.id}
          onMouseDown={() => onSelect(record)}
          disabled={isSelected(record.id)}
          className="truncate"
        >
          <span className="font-mono text-xs text-fg-muted">
            {record.id.slice(0, 8)}
          </span>
          {record.natural_name && (
            <span className="ml-2 text-fg">{record.natural_name}</span>
          )}
          {record.collection && record.collection !== currentCollection && (
            <CollectionMarker name={record.collection} />
          )}
        </ListButton>
      ))}
    </div>
  )
}

interface SingleProps {
  schemaName: string
  value: string | undefined
  onChange: (id: string | undefined) => void
  id?: string
  'aria-describedby'?: string
  'aria-label'?: string
  'aria-invalid'?: boolean
  required?: boolean
  placeholder?: string
  className?: string
}

/** Search-as-you-type picker for a single record reference, scoped to one schema. */
export function RecordSearchPicker({
  schemaName,
  value,
  onChange,
  id,
  'aria-describedby': ariaDescribedby,
  'aria-label': ariaLabel,
  'aria-invalid': ariaInvalid,
  required,
  placeholder,
  className,
}: SingleProps) {
  const [search, setSearch] = useState('')
  const [open, setOpen] = useState(false)
  // Only populated when `value` isn't covered by the current search
  // results — e.g. right after loading a record whose reference points
  // outside the default/unfiltered first page.
  const [fetchedRecord, setFetchedRecord] = useState<CivexRecord | null>(null)
  const { results, loading } = useRecordSearch(schemaName, search)
  const currentCollection = useCollectionName()

  const selectedRecord = value
    ? (results.find((r) => r.id === value) ??
      (fetchedRecord?.id === value ? fetchedRecord : null))
    : null

  useEffect(() => {
    if (!value || selectedRecord) return
    let cancelled = false
    recordsApi
      .get(value)
      .then((r) => {
        if (!cancelled) setFetchedRecord(r)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [value, selectedRecord])

  function handleFocus() {
    setOpen(true)
  }

  function handleSelect(record: CivexRecord) {
    onChange(record.id)
    setOpen(false)
    setSearch('')
  }

  function handleClear() {
    onChange(undefined)
    setSearch('')
  }

  const displayValue = value
    ? selectedRecord
      ? recordLabel(selectedRecord)
      : value.slice(0, 8)
    : search

  return (
    <div className={`relative ${className ?? ''}`}>
      <Input
        id={id}
        aria-describedby={ariaDescribedby}
        aria-label={ariaLabel}
        aria-invalid={ariaInvalid}
        required={required}
        aria-required={required}
        type="text"
        value={displayValue}
        onChange={(e) => {
          setSearch(e.target.value)
          onChange(undefined)
          setOpen(true)
        }}
        onFocus={handleFocus}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder={placeholder ?? `Search ${schemaName} records…`}
        className={value ? 'w-full pr-8' : 'w-full'}
      />
      {value && (
        <IconButton
          icon={X}
          onMouseDown={handleClear}
          className="absolute right-1 top-1/2 -translate-y-1/2"
          aria-label="Clear selection"
        />
      )}
      {open && (
        <ResultsDropdown
          currentCollection={currentCollection}
          loading={loading}
          results={results}
          emptyMessage="No records found"
          isSelected={(id) => id === value}
          onSelect={handleSelect}
        />
      )}
    </div>
  )
}

interface MultiProps {
  schemaName: string
  value: string[]
  onChange: (ids: string[]) => void
  id?: string
  'aria-describedby'?: string
  'aria-label'?: string
  'aria-invalid'?: boolean
  placeholder?: string
  className?: string
}

/** Search-as-you-type picker for a list of record references, scoped to one schema. */
export function MultiRecordSearchPicker({
  schemaName,
  value,
  onChange,
  id,
  'aria-describedby': ariaDescribedby,
  'aria-label': ariaLabel,
  'aria-invalid': ariaInvalid,
  placeholder,
  className,
}: MultiProps) {
  const [search, setSearch] = useState('')
  const [open, setOpen] = useState(false)
  const { results, loading } = useRecordSearch(schemaName, search)
  const currentCollection = useCollectionName()

  const resultLabels = useMemo(
    () => Object.fromEntries(results.map((r) => [r.id, recordLabel(r)])),
    [results],
  )
  // Only populated for selected ids not covered by the current search
  // results — e.g. previously-selected records outside the default page.
  const [fetchedLabels, setFetchedLabels] = useState<Record<string, string>>({})
  const labels = { ...fetchedLabels, ...resultLabels }

  useEffect(() => {
    const missing = value.filter((v) => !(v in labels))
    if (!missing.length) return
    let cancelled = false
    Promise.all(
      missing.map((recordId) =>
        recordsApi
          .get(recordId)
          .then((r) => [recordId, recordLabel(r)] as const)
          .catch(() => [recordId, recordId.slice(0, 8)] as const),
      ),
    ).then((pairs) => {
      if (cancelled) return
      setFetchedLabels((prev) => {
        const next = { ...prev }
        for (const [recordId, label] of pairs) next[recordId] = label
        return next
      })
    })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, resultLabels])

  function handleSelect(record: CivexRecord) {
    if (!value.includes(record.id)) {
      onChange([...value, record.id])
    }
    setSearch('')
  }

  function removeId(recordId: string) {
    onChange(value.filter((v) => v !== recordId))
  }

  return (
    <div className={`relative ${className ?? ''}`}>
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-1">
          {value.map((recordId) => (
            <Chip
              key={recordId}
              onRemove={() => removeId(recordId)}
              removeLabel="Remove"
            >
              {labels[recordId] ?? recordId.slice(0, 8)}
            </Chip>
          ))}
        </div>
      )}
      <Input
        id={id}
        aria-describedby={ariaDescribedby}
        aria-label={ariaLabel}
        aria-invalid={ariaInvalid}
        type="text"
        value={search}
        onChange={(e) => {
          setSearch(e.target.value)
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder={placeholder ?? `Search ${schemaName} records…`}
        className="w-full"
      />
      {open && (
        <ResultsDropdown
          currentCollection={currentCollection}
          loading={loading}
          results={results}
          emptyMessage="No records found"
          isSelected={(recordId) => value.includes(recordId)}
          onSelect={handleSelect}
        />
      )}
    </div>
  )
}
