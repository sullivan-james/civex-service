import { useEffect, useMemo, useRef, useState } from 'react'
import { recordsApi, type CivexRecord } from '../../api/records'
import { Input } from '../ui'
import { X } from '../ui/icons'

export function recordLabel(r: CivexRecord): string {
  return r.natural_name ?? r.id.slice(0, 8)
}

/** Debounced schema-scoped record search, shared by the single- and multi-select pickers below. */
function useRecordSearch(schemaName: string, search: string) {
  const [results, setResults] = useState<CivexRecord[]>([])
  const [loading, setLoading] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!schemaName) return
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(async () => {
      setLoading(true)
      try {
        const records = await recordsApi.searchBySchema(
          schemaName,
          search || undefined,
        )
        setResults(records)
      } finally {
        setLoading(false)
      }
    }, 250)
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [schemaName, search])

  return { results, loading }
}

function ResultsDropdown({
  loading,
  results,
  emptyMessage,
  isSelected,
  onSelect,
}: {
  loading: boolean
  results: CivexRecord[]
  emptyMessage: string
  isSelected: (id: string) => boolean
  onSelect: (record: CivexRecord) => void
}) {
  return (
    <div className="absolute z-10 mt-1 w-full bg-canvas border border-border rounded-md shadow-sm max-h-48 overflow-y-auto text-sm">
      {loading && <div className="px-3 py-2 text-fg-muted">Loading…</div>}
      {!loading && results.length === 0 && (
        <div className="px-3 py-2 text-fg-muted italic">{emptyMessage}</div>
      )}
      {results.map((record) => (
        <button
          key={record.id}
          type="button"
          onMouseDown={() => onSelect(record)}
          disabled={isSelected(record.id)}
          className="w-full text-left px-3 py-2 hover:bg-canvas-subtle truncate disabled:opacity-40 disabled:cursor-default"
        >
          <span className="font-mono text-xs text-fg-muted">
            {record.id.slice(0, 8)}
          </span>
          {record.natural_name && (
            <span className="ml-2 text-fg">{record.natural_name}</span>
          )}
        </button>
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
        <button
          type="button"
          onMouseDown={handleClear}
          className="absolute right-2 top-1/2 -translate-y-1/2 text-fg-muted hover:text-fg"
          aria-label="Clear selection"
        >
          <X size={14} />
        </button>
      )}
      {open && (
        <ResultsDropdown
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
  'aria-invalid': ariaInvalid,
  placeholder,
  className,
}: MultiProps) {
  const [search, setSearch] = useState('')
  const [open, setOpen] = useState(false)
  const { results, loading } = useRecordSearch(schemaName, search)

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
            <span
              key={recordId}
              className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-canvas-subtle border border-border text-xs text-fg"
            >
              {labels[recordId] ?? recordId.slice(0, 8)}
              <button
                type="button"
                onClick={() => removeId(recordId)}
                aria-label="Remove"
                className="text-fg-muted hover:text-danger"
              >
                <X size={12} />
              </button>
            </span>
          ))}
        </div>
      )}
      <Input
        id={id}
        aria-describedby={ariaDescribedby}
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
