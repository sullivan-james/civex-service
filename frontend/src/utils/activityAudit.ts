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
    case 'release':
      return describeReleaseEntry(entry)
    case 'view': {
      const snap = (entry.new_data ?? entry.old_data ?? {}) as { name?: string }
      const word = 'Saved filter'
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
    case 'release': {
      const name = (entry.new_data?.name ?? entry.old_data?.name) as
        string | undefined
      return name
        ? { to: `/releases/${encodeURIComponent(name)}`, label: 'Release' }
        : null
    }
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
  view: ['saved filter', 'saved filters'],
  dashboard: ['Analytics page', 'Analytics pages'],
  note: ['note', 'notes'],
  release: ['release', 'releases'],
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
  const summary = describeEvent(event)
  const done = event.already_done
  if (!done || done.count < 1) return summary
  const said = alreadyDeleted(done, !!event.entry)
  return {
    ...summary,
    detail: summary.detail ? `${summary.detail}. ${said}` : said,
  }
}

/** What the server found already made, as a plain statement: for one change
 * "Already deleted on the server by X", for a batch "8 already deleted on the
 * server by X". */
function alreadyDeleted(
  done: NonNullable<AuditEvent['already_done']>,
  single: boolean,
): string {
  const own = done.own ?? 0
  const who: string[] = []
  if (done.by.length) who.push(`by ${done.by.join(', ')}`)
  if (own) {
    const devices = done.own_devices?.length
      ? ` (${done.own_devices.join(', ')})`
      : ''
    who.push(`from another of your devices${devices}`)
  }
  const tail = who.length ? ` ${who.join(' and ')}` : ''
  const lead = single ? 'Already' : `${done.count.toLocaleString()} already`
  return `${lead} deleted on the server${tail}`
}

function describeEvent(event: AuditEvent): AuditSummary {
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
    default:
      return {
        title: `${batch.kind} (${items(total)})`,
        detail: describeParts(event.parts),
      }
  }
}

/** A note's entry in words: added, replied, edited, resolved, reopened,
 * deleted or brought back, with what it says. A thread is resolved on the
 * note that starts it, so resolving and reopening are said of the thread. */
function describeNoteEntry(entry: AuditLogEntry): AuditSummary {
  const isReply = !!(entry.new_data?.thread_id ?? entry.old_data?.thread_id)
  const noun = isReply ? 'Reply' : 'Note'
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
      return { title: isReply ? 'Replied to a note' : 'Note added', detail }
    case 'delete':
      return { title: `${noun} deleted`, detail }
    case 'restore':
      return { title: `${noun} brought back`, detail: null }
    case 'purge':
      return { title: `${noun} permanently deleted`, detail: null }
    default: {
      const resolved = changed('resolved_at')
      if (resolved)
        return {
          title: resolved.after ? 'Thread resolved' : 'Thread reopened',
          detail,
        }
      return { title: `${noun} edited`, detail }
    }
  }
}

/** A release made, its details corrected, or withdrawn (`domain/release`). */
function describeReleaseEntry(entry: AuditLogEntry): AuditSummary {
  const before = (entry.old_data ?? {}) as { withdrawn_at?: string | null }
  const after = (entry.new_data ?? {}) as {
    name?: string
    title?: string
    withdrawn_at?: string | null
    withdrawn_reason?: string | null
  }
  const what = `Release${after.name ? ` ${after.name}` : ''}`
  if (entry.action === 'create')
    return { title: `${what} made`, detail: after.title ?? null }
  if (after.withdrawn_at && !before.withdrawn_at)
    return {
      title: `${what} withdrawn`,
      detail: after.withdrawn_reason ?? null,
    }
  return { title: `${what}: details corrected`, detail: null }
}
