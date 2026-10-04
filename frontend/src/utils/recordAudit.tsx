import type { AuditLogEntry } from '../api/audit'
import { AuditChangeSummary } from '../components/audit/AuditChanges'
import type { AuditSummary } from './schemaAudit'

/** Human-readable title + a one-line summary of what changed for a record
 * audit entry. The changes themselves are worked out by the server
 * (`entry.changes`), so a renamed or deleted field, or a delete that predates
 * name-keyed snapshots, reads the same as any other entry. */
export function describeAuditEntry(entry: AuditLogEntry): AuditSummary {
  const changes = (
    <AuditChangeSummary changes={entry.changes} action={entry.action} />
  )
  const detail = entry.changes.length ? changes : null
  switch (entry.action) {
    case 'create':
      return { title: 'Record created', detail }
    case 'delete':
      return {
        title: 'Record deleted',
        detail: detail ?? 'Moved to Recently Deleted.',
      }
    case 'restore':
      return { title: 'Record restored', detail: null }
    case 'purge':
      return { title: 'Record permanently deleted', detail }
    case 'update':
      return { title: 'Record updated', detail }
    default:
      return { title: `Record ${entry.action}`, detail: null }
  }
}
