import type { AuditEvent, AuditLogEntry, AuditPart } from '../api/audit'
import { describeAuditEntry as describeCollectionEntry } from './collectionAudit'
import { describeAuditEntry as describeRecordEntry } from './recordAudit'
import {
  describeAuditEntry as describeSchemaEntry,
  type AuditSummary,
} from './schemaAudit'

/** The title and detail for an entry about anything, picking the describer by
 * what the entry is about. For the whole-project feed. */
export function describeAnyAuditEntry(entry: AuditLogEntry): AuditSummary {
  switch (entry.entity_type) {
    case 'record':
      return describeRecordEntry(entry)
    case 'schema':
    case 'field':
      return describeSchemaEntry(entry)
    case 'dataset':
      return describeCollectionEntry(entry)
    case 'dashboard':
      return { title: 'Analytics page edited', detail: null }
    case 'note':
      return describeNoteEntry(entry)
    case 'view': {
      // A saved view with a summary is an analysis; say which when the
      // entry holds the whole view (an edit keeps only what changed).
      const snap = (entry.new_data ?? entry.old_data ?? {}) as {
        name?: string
        summary?: unknown
      }
      const whole = 'summary' in snap
      const word = snap.summary
        ? 'Analysis'
        : whole
          ? 'Saved list'
          : 'Saved view'
      return {
        title: `${word}${snap.name ? ` “${snap.name}”` : ''} ${PAST[entry.action] ?? entry.action}`,
        detail: null,
      }
    }
    default: {
      const name = (entry.new_data?.name ?? entry.old_data?.name) as
        string | undefined
      return {
        title: `${entry.entity_type[0].toUpperCase()}${entry.entity_type.slice(1)}${name ? ` "${name}"` : ''} ${entry.action}d`,
        detail: null,
      }
    }
  }
}

/** Where to open the thing an entry is about, with what to call the link; null
 * when there is nowhere (a view, or something purged). */
export function auditEntryTarget(
  entry: AuditLogEntry,
): { to: string; label: string } | null {
  if (entry.action === 'purge') return null
  switch (entry.entity_type) {
    case 'record':
      return { to: `/records/${entry.entity_id}`, label: 'Record' }
    case 'schema':
      return { to: `/schemas/${entry.entity_id}`, label: 'Schema' }
    case 'field': {
      const schemaId = (entry.new_data?.schema_id ??
        entry.old_data?.schema_id) as string | undefined
      return schemaId ? { to: `/schemas/${schemaId}`, label: 'Schema' } : null
    }
    case 'dataset':
      return { to: `/collections/${entry.entity_id}`, label: 'Collection' }
    case 'dashboard':
      return { to: '/analytics', label: 'Analytics' }
    case 'note': {
      const recordId = (entry.new_data?.record_id ??
        entry.old_data?.record_id) as string | undefined
      return recordId
        ? { to: `/records/${recordId}?tab=notes`, label: 'Record' }
        : null
    }
    default:
      return null
  }
}

const NOUNS: Record<string, [string, string]> = {
  record: ['record', 'records'],
  schema: ['schema', 'schemas'],
  field: ['field', 'fields'],
  dataset: ['collection', 'collections'],
  view: ['saved view', 'saved views'],
  dashboard: ['Analytics page', 'Analytics pages'],
  note: ['note', 'notes'],
}

const PAST: Record<string, string> = {
  create: 'created',
  update: 'edited',
  delete: 'deleted',
  restore: 'restored',
  purge: 'permanently deleted',
}

function count(n: number, entityType: string): string {
  const [one, many] = NOUNS[entityType] ?? [entityType, `${entityType}s`]
  return `${n.toLocaleString()} ${n === 1 ? one : many}`
}

/** What a batch did, in words: "1,200 records edited, 4 records created". */
export function describeParts(parts: AuditPart[]): string {
  return parts
    .map(
      (p) => `${count(p.count, p.entity_type)} ${PAST[p.action] ?? p.action}`,
    )
    .join(', ')
}

/** The title and detail of a line of history: a single change describes itself,
 * and a batch says what kind of operation it was and what it did. */
export function describeAuditEvent(event: AuditEvent): AuditSummary {
  if (event.entry) return describeAnyAuditEntry(event.entry)
  const batch = event.batch!
  const total = event.parts.reduce((n, p) => n + p.count, 0)
  const items = (n: number) =>
    `${n.toLocaleString()} ${n === 1 ? 'item' : 'items'}`
  switch (batch.kind) {
    case 'import':
      return {
        title: `Imported ${batch.label ?? 'data'}`,
        detail: describeParts(event.parts),
      }
    case 'workflow':
      return {
        title: `Workflow “${batch.label ?? 'run'}” made ${items(total)} changes`,
        detail: describeParts(event.parts),
      }
    case 'delete':
      return {
        title: `Deleted ${describeParts(event.parts).replace(/ deleted/g, '')}`,
        detail: null,
      }
    case 'restore':
      return {
        title: `Restored ${describeParts(event.parts).replace(/ restored/g, '')}`,
        detail: null,
      }
    case 'purge':
      return {
        title: `Permanently deleted ${describeParts(event.parts).replace(/ permanently deleted/g, '')}`,
        detail: null,
      }
    case 'move':
      return {
        title: `Moved ${describeParts(event.parts).replace(/ updated/g, '')}`,
        detail: null,
      }
    case 'edit':
      return {
        title: `Edited ${describeParts(event.parts).replace(/ updated/g, '')}`,
        detail: batch.label ? `Changed ${batch.label}` : null,
      }
    case 'review':
      return {
        title: `Marked ${count(total, 'record')} as ${(batch.label ?? 'reviewed').toLowerCase()}`,
        detail: null,
      }
    default:
      return {
        title: `${batch.kind} (${items(total)})`,
        detail: describeParts(event.parts),
      }
  }
}

/** A note's entry in words: added, edited, resolved, reopened, deleted or
 * brought back, with what it says. */
function describeNoteEntry(entry: AuditLogEntry): AuditSummary {
  const changed = (field: string) =>
    entry.changes.find((c) => c.field === field)
  const said = (entry.new_data?.body ??
    entry.old_data?.body ??
    changed('body')?.after) as string | undefined
  const detail = said
    ? `“${said.length > 140 ? `${said.slice(0, 140)}…` : said}”`
    : null
  switch (entry.action) {
    case 'create':
      return { title: 'Note added', detail }
    case 'delete':
      return { title: 'Note deleted', detail }
    case 'restore':
      return { title: 'Note brought back', detail: null }
    case 'purge':
      return { title: 'Note permanently deleted', detail: null }
    default: {
      const resolved = changed('resolved_at')
      if (resolved)
        return {
          title: resolved.after ? 'Note resolved' : 'Note reopened',
          detail,
        }
      return { title: 'Note edited', detail }
    }
  }
}
