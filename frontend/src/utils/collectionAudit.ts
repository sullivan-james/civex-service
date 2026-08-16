import type { AuditLogEntry } from '../api/audit'
import type { AuditSummary } from './schemaAudit'

function describeValue(v: unknown): string {
  return typeof v === 'string' && v ? `"${v}"` : '(none)'
}

/** Human-readable title + before/after detail for a collection audit entry. */
export function describeAuditEntry(entry: AuditLogEntry): AuditSummary {
  const oldData = entry.old_data
  const newData = entry.new_data
  const name = (newData?.name ?? oldData?.name) as string | undefined

  switch (entry.action) {
    case 'create':
      return { title: `Collection "${name}" created`, detail: null }
    case 'delete':
      return {
        title: `Collection "${name}" deleted`,
        detail: 'Moved to Recently Deleted, along with every record in it.',
      }
    case 'restore':
      return {
        title: `Collection "${name}" restored`,
        detail: 'Records cascade-deleted with it were restored too.',
      }
    case 'purge':
      return { title: `Collection "${name}" permanently deleted`, detail: null }
    case 'update': {
      const changes: string[] = []
      if (oldData?.name !== newData?.name) {
        changes.push(
          `renamed "${String(oldData?.name)}" → "${String(newData?.name)}"`,
        )
      }
      if (oldData?.description !== newData?.description) {
        changes.push(
          `description ${describeValue(oldData?.description)} → ${describeValue(newData?.description)}`,
        )
      }
      return {
        title: `Collection "${name}" updated`,
        detail: changes.length ? changes.join('; ') : null,
      }
    }
    default:
      return { title: `Collection "${name}" ${entry.action}`, detail: null }
  }
}
