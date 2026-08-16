import type { AuditLogEntry } from '../api/audit'
import { summarise as summariseRestrictions } from './restrictions'

export interface AuditSummary {
  title: string
  detail: string | null
}

function describeValue(v: unknown): string {
  return typeof v === 'string' && v ? `"${v}"` : '(none)'
}

function describeSchemaChange(entry: AuditLogEntry): AuditSummary {
  const oldData = entry.old_data
  const newData = entry.new_data
  const name = (newData?.name ?? oldData?.name) as string | undefined

  switch (entry.action) {
    case 'create':
      return { title: `Schema "${name}" created`, detail: null }
    case 'delete':
      return {
        title: `Schema "${name}" deleted`,
        detail:
          'Moved to Recently Deleted, along with every record typed by it.',
      }
    case 'restore':
      return {
        title: `Schema "${name}" restored`,
        detail: 'Records cascade-deleted with it were restored too.',
      }
    case 'purge':
      return { title: `Schema "${name}" permanently deleted`, detail: null }
    case 'update': {
      const changes: string[] = []
      if (oldData?.name !== newData?.name) {
        changes.push(
          `renamed "${String(oldData?.name)}" → "${String(newData?.name)}"`,
        )
      }
      if (oldData?.label !== newData?.label) {
        changes.push(
          `label ${describeValue(oldData?.label)} → ${describeValue(newData?.label)}`,
        )
      }
      if (oldData?.description !== newData?.description) {
        changes.push('description changed')
      }
      if (
        JSON.stringify(oldData?.display_fields) !==
        JSON.stringify(newData?.display_fields)
      ) {
        changes.push('display fields changed')
      }
      return {
        title: `Schema "${name}" updated`,
        detail: changes.length ? changes.join('; ') : null,
      }
    }
    default:
      return { title: `Schema "${name}" ${entry.action}`, detail: null }
  }
}

function describeFieldChange(entry: AuditLogEntry): AuditSummary {
  const oldData = entry.old_data
  const newData = entry.new_data
  const name = (newData?.name ?? oldData?.name) as string | undefined
  const dtype = (newData?.dtype ?? oldData?.dtype) as string | undefined

  switch (entry.action) {
    case 'create':
      return {
        title: `Field "${name}" added`,
        detail: dtype ? `Type: ${dtype}` : null,
      }
    case 'delete':
      return { title: `Field "${name}" removed`, detail: null }
    case 'update': {
      const changes: string[] = []
      if (oldData?.name !== newData?.name) {
        changes.push(
          `renamed "${String(oldData?.name)}" → "${String(newData?.name)}"`,
        )
      }
      if (oldData?.label !== newData?.label) {
        changes.push(
          `label ${describeValue(oldData?.label)} → ${describeValue(newData?.label)}`,
        )
      }
      if (oldData?.required !== newData?.required) {
        changes.push(newData?.required ? 'made required' : 'made optional')
      }
      if (
        JSON.stringify(oldData?.restrictions) !==
        JSON.stringify(newData?.restrictions)
      ) {
        const before = summariseRestrictions(
          (oldData?.restrictions as Record<string, unknown>) ?? {},
          dtype ?? '',
        )
        const after = summariseRestrictions(
          (newData?.restrictions as Record<string, unknown>) ?? {},
          dtype ?? '',
        )
        changes.push(
          `restrictions ${before || '(none)'} → ${after || '(none)'}`,
        )
      }
      if (oldData?.default_value !== newData?.default_value) {
        changes.push('default value changed')
      }
      return {
        title: `Field "${name}" updated`,
        detail: changes.length ? changes.join('; ') : null,
      }
    }
    default:
      return { title: `Field "${name}" ${entry.action}`, detail: null }
  }
}

/** Human-readable title + before/after detail for a schema or field audit entry. */
export function describeAuditEntry(entry: AuditLogEntry): AuditSummary {
  return entry.entity_type === 'field'
    ? describeFieldChange(entry)
    : describeSchemaChange(entry)
}
