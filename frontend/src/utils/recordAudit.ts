import type { AuditLogEntry } from '../api/audit'
import type { AuditSummary } from './schemaAudit'
import { displayLabel } from './naming'

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '(none)'
  if (typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) {
    return value.length ? value.map(formatValue).join(', ') : '(none)'
  }
  if (typeof value === 'object' && 'filename' in (value as object)) {
    return (value as { filename: string }).filename
  }
  return String(value)
}

// old_data/new_data are full record snapshots ({id, data, created_at, ...})
// -- only the `data` sub-object holds field values, and only create/update
// log it name-keyed on both sides (delete/purge/restore mix in a raw,
// id-keyed snapshot), so only those two get a field diff.
function diffFields(entry: AuditLogEntry): string[] {
  if (entry.action !== 'create' && entry.action !== 'update') return []
  const before =
    (entry.old_data?.data as Record<string, unknown> | undefined) ?? null
  const after =
    (entry.new_data?.data as Record<string, unknown> | undefined) ?? null
  const fields = new Set([
    ...Object.keys(before ?? {}),
    ...Object.keys(after ?? {}),
  ])
  const changes: { field: string; text: string }[] = []
  for (const field of fields) {
    const b = before?.[field] ?? null
    const a = after?.[field] ?? null
    if (JSON.stringify(b) !== JSON.stringify(a)) {
      const value =
        entry.action === 'create'
          ? formatValue(a)
          : `${formatValue(b)} → ${formatValue(a)}`
      changes.push({ field, text: `${displayLabel(field)} ${value}` })
    }
  }
  return changes
    .sort((x, y) => x.field.localeCompare(y.field))
    .map((c) => c.text)
}

/** Human-readable title + before/after detail for a record audit entry. */
export function describeAuditEntry(entry: AuditLogEntry): AuditSummary {
  switch (entry.action) {
    case 'create':
      return {
        title: 'Record created',
        detail: diffFields(entry).join('; ') || null,
      }
    case 'delete':
      return { title: 'Record deleted', detail: 'Moved to Recently Deleted.' }
    case 'restore':
      return { title: 'Record restored', detail: null }
    case 'purge':
      return { title: 'Record permanently deleted', detail: null }
    case 'update': {
      const changes = diffFields(entry)
      return {
        title: 'Record updated',
        detail: changes.length ? changes.join('; ') : null,
      }
    }
    default:
      return { title: `Record ${entry.action}`, detail: null }
  }
}
