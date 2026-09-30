import { Fragment, type ReactNode } from 'react'
import type { AuditLogEntry } from '../api/audit'
import type { AuditSummary } from './schemaAudit'
import type { Field, Schema } from '../api/schemas'
import { displayLabel } from './naming'
import { FetchedReferenceLink } from '../components/records/ReferenceLink'

function formatValue(value: unknown, field: Field | undefined): ReactNode {
  if (value === null || value === undefined) return '(none)'
  if (field?.type === 'reference' && typeof value === 'string')
    return <FetchedReferenceLink id={value} />
  if (field?.type === 'reference_list' && Array.isArray(value)) {
    return value.length
      ? value.map((v, i) => (
          <Fragment key={v as string}>
            {i > 0 && ', '}
            <FetchedReferenceLink id={v as string} />
          </Fragment>
        ))
      : '(none)'
  }
  if (typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) {
    return value.length
      ? value.map((v) => formatValue(v, undefined)).join(', ')
      : '(none)'
  }
  if (typeof value === 'object' && 'filename' in (value as object)) {
    return (value as { filename: string }).filename
  }
  return String(value)
}

function joinNodes(nodes: ReactNode[], separator: string): ReactNode {
  return nodes.map((node, i) => (
    <Fragment key={i}>
      {i > 0 && separator}
      {node}
    </Fragment>
  ))
}

// old_data/new_data are full record snapshots ({id, data, created_at, ...})
// -- only the `data` sub-object holds field values, and only create/update
// log it name-keyed on both sides (delete/purge/restore mix in a raw,
// id-keyed snapshot), so only those two get a field diff.
function diffFields(
  entry: AuditLogEntry,
  schema: Schema | undefined,
): ReactNode {
  if (entry.action !== 'create' && entry.action !== 'update') return null
  const before =
    (entry.old_data?.data as Record<string, unknown> | undefined) ?? null
  const after =
    (entry.new_data?.data as Record<string, unknown> | undefined) ?? null
  const fieldsByName = new Map((schema?.fields ?? []).map((f) => [f.name, f]))
  const names = new Set([
    ...Object.keys(before ?? {}),
    ...Object.keys(after ?? {}),
  ])
  const changes: { field: string; text: ReactNode }[] = []
  for (const name of names) {
    const b = before?.[name] ?? null
    const a = after?.[name] ?? null
    if (JSON.stringify(b) !== JSON.stringify(a)) {
      const field = fieldsByName.get(name)
      const value =
        entry.action === 'create' ? (
          formatValue(a, field)
        ) : (
          <>
            {formatValue(b, field)} → {formatValue(a, field)}
          </>
        )
      changes.push({
        field: name,
        text: (
          <>
            {displayLabel(name)} {value}
          </>
        ),
      })
    }
  }
  if (!changes.length) return null
  changes.sort((x, y) => x.field.localeCompare(y.field))
  return joinNodes(
    changes.map((c) => c.text),
    '; ',
  )
}

/** Human-readable title + before/after detail for a record audit entry.
 * `schema` (the record's current schema) is used to render reference
 * field diffs as links -- omit it and they fall back to plain ids. */
export function describeAuditEntry(
  entry: AuditLogEntry,
  schema?: Schema,
): AuditSummary {
  switch (entry.action) {
    case 'create':
      return { title: 'Record created', detail: diffFields(entry, schema) }
    case 'delete':
      return { title: 'Record deleted', detail: 'Moved to Recently Deleted.' }
    case 'restore':
      return { title: 'Record restored', detail: null }
    case 'purge':
      return { title: 'Record permanently deleted', detail: null }
    case 'update':
      return { title: 'Record updated', detail: diffFields(entry, schema) }
    default:
      return { title: `Record ${entry.action}`, detail: null }
  }
}
